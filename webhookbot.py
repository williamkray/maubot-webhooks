from __future__ import annotations

import json
import re
from typing import Optional, Type, Callable

from aiohttp.abc import Request
from aiohttp.web_response import Response
from maubot import Plugin
from maubot.handlers import web
from mautrix.types import RoomID, MessageType
from mautrix.util.config import ConfigUpdateHelper, BaseProxyConfig

# Debug logging is enabled for all webhook requests to help with endpoint configuration
# Check the maubot logs to see request payloads, query parameters, and formatted messages
# 
# Authentication supports both single tokens and lists of tokens per endpoint:
# - Single token: auth_token: 'MyToken123'
# - Multiple tokens: auth_token: ['Token1', 'Token2', 'Token3']
#
# Token delivery methods:
# - Query parameter: ?token=MyToken123 (default, works for all endpoints)
# - Authorization header: Authorization: Bearer MyToken123 (requires enable_bearer_auth: true)

class WebhookConfig(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy_dict("endpoints")
        helper.copy('tokens')
        helper.copy('enable_bearer_auth')


class WebhookBot(Plugin):
    param_matcher: re.Pattern

    async def start(self) -> None:
        self.log.info('Starting webhook bot!')

        self.log.info('Loading config...')
        self.config.load_and_update()

        self.log.info('Compiling regex...')
        self.param_matcher = re.compile('\\${([^}]+)}')

        self.log.info('Initialised!')

    def validate_token(self, req: Request, endpoint: Optional[dict] = None) -> bool:
        request_token = None
        
        # Try to get token from Authorization header first (if enabled)
        enable_bearer = self.config.get('enable_bearer_auth', False)
        if enable_bearer:
            auth_header = req.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                request_token = auth_header[7:]  # Remove 'Bearer ' prefix
                self.log.debug(f"Token extracted from Authorization header")
        
        # Fall back to query parameter token if no Bearer token found or Bearer auth disabled
        if request_token is None:
            try:
                request_token = req.query['token']
                self.log.debug(f"Token extracted from query parameter")
            except KeyError:
                self.log.error('No token provided in request (neither Authorization header nor query parameter)')
                return False
        
        # Check endpoint-specific auth_token first
        if endpoint and endpoint.get('auth_token'):
            auth_token = endpoint['auth_token']
            
            # Support both single token (string) and multiple tokens (list)
            if isinstance(auth_token, str):
                # Single token - direct comparison
                if request_token == auth_token:
                    return True
            elif isinstance(auth_token, list):
                # Multiple tokens - check if request token is in the list
                if request_token in auth_token:
                    return True
        
        # Fall back to global tokens for backward compatibility
        valid_tokens: list = self.config.get('tokens', [])
        return request_token in valid_tokens

    def get_endpoint(self, name) -> Optional[dict]:
        data: dict = self.config.get("endpoints", {})
        if name in data.keys():
            return data[name]
        else:
            return None

    def format_message(self, endpoint: dict, lookup: Callable[[str], any]) -> str:
        template = endpoint.get('template')

        params = self.param_matcher.findall(template)
        msg_content = template
        missing_vars = []

        for param_name in params:
            replacement = lookup(param_name)
            if replacement is None:
                replacement = '(???)'
                missing_vars.append(param_name)
            msg_content = msg_content.replace(f'${{{param_name}}}', replacement)

        # If any variables are missing, return None to trigger error handling
        if missing_vars:
            return None
        
        return msg_content

    @web.get("/{endpoint}")
    async def execute_get(self, req: Request) -> Response:
        return await self._execute_webhook(req, "GET")

    @web.post("/{endpoint}")
    async def execute_post(self, req: Request) -> Response:
        return await self._execute_webhook(req, "POST")

    async def _execute_webhook(self, req: Request, method: str) -> Response:
        endpoint_name = req.match_info["endpoint"]
        endpoint = self.get_endpoint(endpoint_name)
        self.log.info(f"Received webhook endpoint {endpoint_name}")

        if not self.validate_token(req, endpoint):
            self.log.error(f'Endpoint {endpoint_name} called with invalid token!')
            return Response(status=403)

        if endpoint is None:
            self.log.error(f'Endpoint {endpoint_name} does not exist')
            return Response(status=404)

        # Check if the HTTP method is allowed for this endpoint
        allowed_methods = endpoint.get('methods', [])
        if not allowed_methods or method not in allowed_methods:
            self.log.error(f'Endpoint {endpoint_name} may not receive {method} requests')
            return Response(status=405)  # Method Not Allowed

        if method == "GET":
            return await self._handle_get_request(req, endpoint, endpoint_name)
        else:  # POST
            return await self._handle_post_request(req, endpoint, endpoint_name)

    async def _handle_get_request(self, req: Request, endpoint: dict, endpoint_name: str) -> Response:
        # Debug: Log the query parameters for troubleshooting
        query_params = dict(req.query)
        # Remove token from debug output for security
        if 'token' in query_params:
            query_params['token'] = '[REDACTED]'
        self.log.info(f"GET request query parameters for endpoint '{endpoint_name}': {query_params}")

        def lookup(key: str) -> str:
            value = req.query.get(key)
            return value

        msg = self.format_message(endpoint, lookup)
        if msg is None:
            # Template variables are missing
            missing_vars = []
            for param_name in self.param_matcher.findall(endpoint.get('template', '')):
                if req.query.get(param_name) is None:
                    missing_vars.append(param_name)
            
            error_msg = f"Missing template variables: {', '.join(missing_vars)}\n\nQuery parameters:\n```\n{query_params}\n```"
            await self._send_error_message(endpoint, endpoint_name, error_msg)
            return Response(status=500)

        room = RoomID(endpoint.get('room_id'))

        # Debug: Log the final formatted message
        self.log.info(f"Formatted message for endpoint '{endpoint_name}': {msg}")

        try:
            await self.client.send_markdown(room, msg, allow_html=True,
                                            msgtype=MessageType.NOTICE if endpoint.get('notice') else MessageType.TEXT)
        except Exception as e:
            self.log.error(f'Failed to send message {msg}: {e}')
            return Response(status=500)

        return Response(status=200)

    async def _handle_post_request(self, req: Request, endpoint: dict, endpoint_name: str) -> Response:
        data: str = await req.text()
        
        # Debug: Log the raw request payload for troubleshooting
        self.log.info(f"POST request payload for endpoint '{endpoint_name}': {data}")

        if endpoint.get('format') == 'JSON':
            try:
                data: dict = json.loads(data)
                # Debug: Log the parsed JSON structure for easier template configuration
                self.log.info(f"Parsed JSON structure for endpoint '{endpoint_name}': {json.dumps(data, indent=2)}")
                
                # Handle nested JSON strings in the parsed data
                data = self._parse_nested_json(data)
                
            except json.JSONDecodeError as e:
                self.log.error(f"Invalid JSON payload for endpoint '{endpoint_name}': {e}")
                # Send raw payload to Matrix instead of failing silently
                await self._send_error_message(endpoint, endpoint_name, f"Invalid JSON payload: {e}\n\nRaw payload:\n```\n{data}\n```")
                return Response(status=400, text="Invalid JSON payload")

            def lookup_json(key: str):
                parts = key.split('.')
                pointer = data

                for part in parts:
                    if pointer is None:
                        return None
                    if '[' in part and ']' in part:
                        # array index assumed here!

                        try:
                            arr_parts = part.split('[')
                            pointer = pointer[arr_parts[0]]
                            arr_index = int(arr_parts[1].split(']')[0])
                            pointer = pointer[arr_index]
                        except (KeyError, IndexError):
                            self.log.error(f'Unknown or invalid key {part}')
                            return None
                    else:
                        try:
                            pointer = pointer[part]
                        except KeyError:
                            self.log.error(f'Unknown or invalid key {part}')
                            return None

                if pointer is not None and not isinstance(pointer, str):
                    pointer = str(pointer)
                return pointer

            try:
                msg = self.format_message(endpoint, lookup_json)
                if msg is None:
                    # Template variables are missing
                    missing_vars = []
                    for param_name in self.param_matcher.findall(endpoint.get('template', '')):
                        if lookup_json(param_name) is None:
                            missing_vars.append(param_name)
                    
                    error_msg = f"Missing template variables: {', '.join(missing_vars)}\n\nParsed JSON:\n```json\n{json.dumps(data, indent=2)}\n```"
                    await self._send_error_message(endpoint, endpoint_name, error_msg)
                    return Response(status=500)
            except Exception as e:
                self.log.error(f"Error formatting message for endpoint '{endpoint_name}': {e}")
                # Send raw JSON to Matrix instead of failing silently
                await self._send_error_message(endpoint, endpoint_name, f"Error formatting message: {e}\n\nParsed JSON:\n```json\n{json.dumps(data, indent=2)}\n```")
                return Response(status=500)
        else:
            msg = self.format_message(endpoint, lambda x: None)
            if msg is None:
                # Template variables are missing for non-JSON endpoints
                missing_vars = []
                for param_name in self.param_matcher.findall(endpoint.get('template', '')):
                    missing_vars.append(param_name)
                
                error_msg = f"Missing template variables: {', '.join(missing_vars)}\n\nThis endpoint does not support template variables."
                await self._send_error_message(endpoint, endpoint_name, error_msg)
                return Response(status=500)

        # Debug: Log the final formatted message
        self.log.info(f"Formatted message for endpoint '{endpoint_name}': {msg}")

        room = RoomID(endpoint.get('room_id'))

        try:
            msg = await self.client.send_markdown(room, msg, allow_html=True,
                                                  msgtype=MessageType.NOTICE if endpoint.get(
                                                      'notice') else MessageType.TEXT)
        except Exception as e:
            self.log.error(f'Failed to send message {msg}: {e}')
            return Response(status=500)

        return Response(status=200)

    def _parse_nested_json(self, data: dict) -> dict:
        """
        Recursively parse nested JSON strings in the data structure.
        This allows accessing nested JSON objects that are stored as strings.
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(value, str):
                    # Try to parse as JSON if it looks like valid JSON
                    trimmed = value.strip()
                    if (trimmed.startswith('{') and trimmed.endswith('}')) or (trimmed.startswith('[') and trimmed.endswith(']')):
                        try:
                            parsed = json.loads(value)
                            result[key] = self._parse_nested_json(parsed)
                            self.log.debug(f"Successfully parsed nested JSON for key '{key}'")
                        except json.JSONDecodeError:
                            # Not valid JSON, keep as string
                            self.log.debug(f"String for key '{key}' looks like JSON but failed to parse, keeping as string")
                            result[key] = value
                    else:
                        result[key] = value
                elif isinstance(value, (dict, list)):
                    result[key] = self._parse_nested_json(value)
                else:
                    result[key] = value
            return result
        elif isinstance(data, list):
            return [self._parse_nested_json(item) for item in data]
        else:
            return data

    async def _send_error_message(self, endpoint: dict, endpoint_name: str, error_content: str) -> None:
        """
        Send an error message to Matrix with the raw content wrapped in a code block.
        """
        try:
            room = RoomID(endpoint.get('room_id'))
            error_msg = f"**Webhook Error for endpoint '{endpoint_name}':**\n\n{error_content}"
            
            await self.client.send_markdown(room, error_msg, allow_html=True,
                                            msgtype=MessageType.NOTICE)
            self.log.info(f"Sent error message to Matrix for endpoint '{endpoint_name}'")
        except Exception as e:
            self.log.error(f"Failed to send error message to Matrix: {e}")

    @classmethod
    def get_config_class(cls) -> Type['BaseProxyConfig']:
        return WebhookConfig

