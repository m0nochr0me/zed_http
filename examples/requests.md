# API notes

Some prose describing the API. Requests in fenced `http` blocks are runnable too.

```http
### health check
GET https://httpbin.org/get?from=markdown HTTP/1.1
Accept: application/json
```

More prose between requests.

```http
POST https://httpbin.org/post HTTP/1.1
Content-Type: application/json

{
  "source": "markdown"
}
```
