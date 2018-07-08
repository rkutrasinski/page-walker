
class DatabasePage(object):
    def __init__(self, conn):
        self.conn = conn

    def pages_list_with_data(self):
        c = self.conn.cursor()
        c.execute("""
            SELECT P.id, P.url, S.time_load, S.file_content_length, R.http_status, F.content_type, E.name
            FROM pages AS P
            LEFT JOIN pages_stats AS S
                ON P.id = S.page_id
            LEFT JOIN requests AS R
                ON P.id = R.page_id AND R.is_main = 1
            LEFT JOIN file_types AS F
                ON P.file_type = F.id
            LEFT JOIN connection_exceptions AS E
                ON P.exception_id = E.id
            WHERE P.status > 0
        """)
        result = c.fetchall()
        data_pages = []
        for row in result:
            page_id, url, time_load, file_content_length, http_status, file_content_type, exception_name = row
            page_data = {
                "id": page_id,
                "url": url,
                "time_load": time_load,
                "http_status": http_status,
                "exception_name": exception_name,
                "file_content_type": file_content_type,
                "file_content_length": file_content_length
            }
            data_pages.append(page_data)
        return data_pages

    def request_stats_for_pages(self):
        data_pages = self._requests_for_pages()
        self._append_data_received_stats(data_pages)
        return data_pages

    def _append_data_received_stats(self, data):
        for page_id, received in self._data_received_stats().items():
            data[page_id]["data_received"] = received

    def _requests_for_pages(self):
        c = self.conn.cursor()
        c.execute("""
            SELECT page_id, COUNT(*), SUM(from_cache)
            FROM requests
            GROUP BY page_id
        """)
        result = c.fetchall()
        all_pages = {}
        for row in result:
            page_id, requests_count, from_cache = row
            all_pages[page_id] = {
                "requests_count": requests_count,
                "from_cache": from_cache
            }
        return all_pages

    # only non-cached requests, because there are cached requests with data_received > 0
    def _data_received_stats(self):
        c = self.conn.cursor()
        c.execute("""
            SELECT page_id, SUM(data_received)
            FROM requests
            WHERE from_cache = 0
            GROUP BY page_id
        """)
        result = c.fetchall()
        all_pages = {}
        for row in result:
            page_id, data_received = row
            all_pages[page_id] = data_received
        return all_pages
