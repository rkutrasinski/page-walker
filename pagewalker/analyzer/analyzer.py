from os import path
from .devtools import remote_debug, response_parser
from pagewalker.utilities import url_utils
from . import database_admin, database_writer, html_parser, html_validator


class Analyzer(object):
    def __init__(self, config):
        self.max_number_pages = config["max_number_pages"]
        self.pages_list_file = config["pages_list_file"]
        self.pages_list_only = config["pages_list_only"]
        self.wait_time_after_load = config["wait_time_after_load"]
        self.scroll_after_load = config["scroll_after_load"]
        self.timeout = config["chrome_timeout"]

        chrome_dir_with_port = path.join(config["chrome_data_dir"], "port_%s" % config["chrome_debugging_port"])
        self.devtools_remote = remote_debug.DevtoolsRemoteDebug(
            config["chrome_headless"],
            config["chrome_close_on_finish"],
            config["chrome_debugging_port"],
            chrome_dir_with_port,
            config["chrome_timeout"],
            config["window_size"],
            config["chrome_binary"],
            config["chrome_ignore_cert"],
            config["current_data_dir"]
        )

        validator_dir_with_port = path.join(config["validator_html_dir"], "port_%s" % config["chrome_debugging_port"])
        self.validator = html_validator.HtmlValidator(
            config["validator_enabled"],
            config["validator_vnu_jar"],
            validator_dir_with_port,
            config["validator_check_css"],
            config["validator_show_warnings"],
            config["java_binary"],
            config["java_stack_size"]
        )

        config_to_save = {
            "wait_time_after_load": self.wait_time_after_load,
            "max_number_pages": self.max_number_pages,
            "window_size": config["window_size"],
            "headless": "Yes" if config["chrome_headless"] else "No",
            "chrome_timeout": config["chrome_timeout"],
            "validator_enabled": "Yes" if config["validator_enabled"] else "No",
            "validator_css": "Yes" if config["validator_check_css"] else "No",
            "validator_warnings": "Yes" if config["validator_show_warnings"] else "No",
            "scroll_after_load": "Yes" if self.scroll_after_load else "No"
        }
        self.db_admin = database_admin.DatabaseAdmin(
            config["start_url"],
            config["sqlite_file"],
            self.pages_list_file,
            config_to_save
        )

    def start_new_analysis(self):
        db_admin = self.db_admin
        db_admin.create_clean_database()
        self.validator.set_db_connection(self.db_admin.get_connection())

        devtools_remote = self.devtools_remote
        devtools_remote.start_session()
        self._save_chrome_version(db_admin, devtools_remote)
        db_admin.add_to_config("vnu_version", self.validator.get_vnu_version())

        if self.pages_list_file and self.pages_list_only:
            self.max_number_pages = db_admin.get_pages_list_count() + 1

        for i in range(0, self.max_number_pages):
            next_page = db_admin.get_next_page()
            if not next_page:
                break
            self._analyze_page(next_page["id"], next_page["url"])
            self.validator.validate_if_full_queue()

        devtools_remote.end_session()
        self.validator.validate()
        db_admin.close_database()

    def _analyze_page(self, page_id, url):
        print("%s. %s" % (page_id, url))

        db_page_writer = database_writer.DatabasePageWriter(
            self.db_admin.get_connection(),
            page_id,
            url
        )
        db_page_writer.change_status_started()

        valid_for_chrome = url_utils.check_valid_for_chrome(url, self.timeout)
        if valid_for_chrome["status"] == "no":
            db_page_writer.change_status_finished(valid_for_chrome["error_name"])
            return
        elif valid_for_chrome["status"] == "file":
            db_page_writer.save_page_as_file(valid_for_chrome["content_type"], valid_for_chrome["content_length"])
            db_page_writer.change_status_finished()
            return

        devtools_remote = self.devtools_remote
        messages = devtools_remote.open_url(url)
        if not messages:
            return

        devtools_parser = response_parser.DevtoolsResponseParser()
        devtools_parser.append_response(messages)

        if self.scroll_after_load:
            devtools_remote.scroll_to_bottom()

        messages = devtools_remote.wait(self.wait_time_after_load)
        devtools_parser.append_response(messages)

        parsed_logs = devtools_parser.get_logs()
        db_page_writer.save_devtools_data(parsed_logs)

        main_request_id = parsed_logs["general"]["main_request_id"]
        self._process_html_code(db_page_writer, main_request_id)
        db_page_writer.change_status_finished()

    def _process_html_code(self, db_writer, request_id):
        html_raw = self.devtools_remote.get_html_raw(request_id)
        html_dom = self.devtools_remote.get_html_dom()
        self._save_new_links(db_writer, html_dom)
        self.validator.add_to_queue(db_writer.get_page_id(), html_raw, html_dom)

    def _save_new_links(self, db_writer, html_dom):
        parser = html_parser.MyHtmlParser(db_writer.get_url())
        parser.feed(html_dom)
        links = parser.get_links()
        db_writer.add_internal_links(links["internal"])

    def _save_chrome_version(self, db_admin, devtools_remote):
        version = devtools_remote.get_version()
        db_admin.add_to_config("chrome_version", version["product"])
        db_admin.add_to_config("devtools_protocol", version["protocolVersion"])
