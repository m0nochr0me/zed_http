; Highlight HTTP methods
(method) @function.method

; Highlight HTTP comments and request separators
[
  (comment)
  (request_separator)
] @comment

; Highlight the request target URL
(request
  url: (target_url) @string.url)

; Highlight HTTP headers
(header name: (header_entity) @property)
(header value: (value) @string)

; Highlight HTTP status codes and status texts
(status_code) @constant.numeric
(status_text) @constant.language

; Highlight HTTP versions
(http_version) @keyword

; Highlight variables (overrides URL/header coloring for {{...}})
(variable) @variable

; Highlight different types of request bodies
(json_body) @string.special
(xml_body) @string.special
(graphql_body) @string.special
(external_body) @string.special
(multipart_form_data) @string.special
(raw_body) @string.special
