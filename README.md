# Maubot webhooks: receive messages in your matrix chat through HTTP(S)

This is a [maubot](https://github.com/maubot/maubot) plugin to dynamically expose and process webhooks.

## Requirements
To use this, you need the [normal maubot dependencies](https://docs.mau.fi/maubot/). That usually means Python 3 with
the maubot package. This guide does not tell you how to run Maubot, please refer to the official docs for that.

## Installation
1. Build the maubot from source using the official [instructions](https://docs.mau.fi/maubot/usage/cli/build.html):
```bash
$ mbc build
```
2. Upload the .mbp file to your maubot instance (click the + next to "Plugins")
3. Create a maubot client if you haven't already ([docs](https://docs.mau.fi/maubot/usage/basic.html))
4. Click the + next to "Instances" to create a new instance
5. Fill out the form to your liking and hit Create
6. Configure the newly created instance

## Configuration
Configuration is done through the accompanying YAML file. An example is provided in this repository.

### Example YAML
The following example YAML provides two endpoints, a POST endpoint and a GET endpoint.
```yaml
endpoints:
  endpointname:
    notice: false
    room_id: '!......@.....'
    format: JSON
    template: 'Test data: ${user.name} is ${user.mood}'
    methods:
      - POST
    auth_token: 'EndpointSpecificToken123'  # Single token
  anotherendpoint:
    notice: true
    room_id: '!......@.....'
    template: 'Test data: ${fromQuery}'
    methods:
      - GET
    auth_token: 'AnotherEndpointToken456'  # Single token
  multiuserendpoint:
    notice: false
    room_id: '!......@.....'
    format: JSON
    template: 'User ${user.name} sent: ${message}'
    methods:
      - POST
    auth_token:  # Multiple tokens for different users
      - 'User1Token789'
      - 'User2Token012'
      - 'User3Token345'

# Authentication configuration
enable_bearer_auth: true  # Enable Bearer token authentication in Authorization headers

tokens:
 - authtoken1
 - authtoken2
```

All webhooks are protected by tokens. You can use either:
- **Global tokens** (defined in the `tokens` list) - work on all endpoints for backward compatibility
- **Per-endpoint tokens** (defined as `auth_token` in each endpoint) - provide unique authentication per webhook

**Per-endpoint tokens support two formats:**
- **Single token**: `auth_token: 'MyToken123'` - only one token accepted
- **Multiple tokens**: `auth_token: ['Token1', 'Token2', 'Token3']` - any of the listed tokens accepted

**Token Delivery Methods:**
- **Query Parameter** (default): `?token=MyToken123` - works for all endpoints
- **Authorization Header** (optional): `Authorization: Bearer MyToken123` - requires `enable_bearer_auth: true`

If an endpoint has an `auth_token` defined, it will only accept tokens from that list. Otherwise, it will accept any of the global tokens. A call without a token or with an invalid token will be ignored and logged.

Endpoint `endpointname` can only be called through POST requests, accepts JSON as input (the only supported input type
for POST requests at the moment) and sends notifications as normal text messages (those will generate a notification
sound by default!). You can find the room ID that the bot sends to in your favourite Matrix client. This bot does not try
to autojoin rooms, so you'll have to invite maubot to your room for this to work.

You can call this webhook with the following data:
```json
{
  "user": {
    "name": "Willem",
    "mood": "happy"
  }
}
```

The endpoint will be available at a URL relative to your maubot instance. For example, if you run maubot at
https://matrix.example.org/_matrix/maubot/# and you call your maubot instance "webhookbot", the callback URL will be
https://matrix.example.org/_matrix/maubot/plugin/webhookbot/endpointname?token=EndpointSpecificToken123

**Alternative with Bearer token** (if `enable_bearer_auth: true`):
```bash
curl -X POST https://matrix.example.org/_matrix/maubot/plugin/webhookbot/endpointname \
  -H "Authorization: Bearer EndpointSpecificToken123" \
  -H "Content-Type: application/json" \
  -d '{"user": {"name": "John", "mood": "happy"}}'
```

The second endpoint, `anotherendpoint`, accepts data through a GET request. As there is no good way to encode JSON in a
GET request, GET endpoints take data from the query string instead. The second endpoint sends messages as notices (usually
means that no notifications will be sent). The callback URL for this endpoint will be https://matrix.example.org/_matrix/maubot/plugin/webhookbot/anotherendpoint?token=AnotherEndpointToken456&fromQuery=itworks123

The above call will send the message `Test data: itworks123` to the defined Matrix room.

**Note:** Endpoints use a simplified URL structure without HTTP method prefixes (e.g., `/endpointname` instead of `/post/endpointname`). The allowed HTTP methods are determined by the endpoint configuration in your YAML file.

## Bearer Token Authentication

When `enable_bearer_auth: true` is set in your configuration, POST endpoints can accept tokens via the `Authorization` header using the Bearer scheme. This is useful for:

- **Security**: Tokens are not exposed in URLs or server logs
- **Standards compliance**: Follows OAuth 2.0 Bearer token standards
- **Integration**: Works with many API clients and libraries that expect Bearer tokens

**Example usage:**
```bash
# Using curl with Bearer token
curl -X POST https://matrix.example.org/_matrix/maubot/plugin/webhookbot/endpointname \
  -H "Authorization: Bearer YourTokenHere" \
  -H "Content-Type: application/json" \
  -d '{"data": "value"}'

# Using Python requests
import requests
headers = {
    'Authorization': 'Bearer YourTokenHere',
    'Content-Type': 'application/json'
}
response = requests.post(
    'https://matrix.example.org/_matrix/maubot/plugin/webhookbot/endpointname',
    headers=headers,
    json={'data': 'value'}
)
```

**Note:** Bearer authentication is only available for POST endpoints. GET endpoints continue to use query parameter tokens for compatibility.

## Formatting
Templates can be formatted through markdown, though the allow_html parameter has also been enabled in the code. Because
YAML allows for newlines and such, the following is a valid endpoint definition:

```yaml
endpoints:
  fancy:
    notice: false
    room_id: '!......@.....'
    format: JSON
    template: |
            **Hello, world!**
            
            Check these _sick___markdown__ features!
            <b>HTML works too!</b>
            
            Remember to use double newlines for a paragraph break!
    methods:
      - POST
      - GET
```

### Troubleshooting
Errors will be logged to the maubot log. Info logs are used to indicate startup and to track calls to the endpoints.

**Debug Logging**: The bot now includes comprehensive debug logging to help you troubleshoot endpoint configuration:
- **POST requests**: Logs the raw request payload and parsed JSON structure
- **GET requests**: Logs all query parameters (with token redacted for security)
- **Message formatting**: Shows the final formatted message before sending to Matrix

This makes it much easier to understand the structure of incoming webhook data and configure your templates accordingly.

If something goes wrong and no error message is logged to the maubot log, check the docker/maubot server output!


## License
This software is released under the AGPL license (see LICENSE.md). If this is a problem for you, I'm happy to discuss dual licensing
for personal or non-profit use; contact me at the email address I used to commit files to this repository
(you can find it in the commit log).