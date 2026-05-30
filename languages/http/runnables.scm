; Show a run button (▶) on each request. The "http-request" tag matches the
; tasks of the same tag in .zed/tasks.json, which invoke scripts/run_http.py.
(
  (request
    (method) @run
  ) @http-request
  (#set! tag http-request)
)
