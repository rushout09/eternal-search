import httpx
from httpx_oauth.oauth2 import OAuth2
import json
import os
from dotenv import load_dotenv

load_dotenv()

# HOST_URL: str = 'https://rushabh.loca.lt'
HOST_URL = os.getenv('HOST_URL')


class BaseServiceProvider:
    CLIENT_ID: str
    CLIENT_SECRET: str
    REDIRECT_URI: str
    REDIRECT_URL: str
    SCOPES: str
    AUTH_URL: str
    TOKEN_URL: str

    @staticmethod
    async def search(search_term: str, client: httpx.AsyncClient, api_url: str, headers: dict, **kwargs) -> list:
        raise NotImplementedError


class GoogleServiceProvider(BaseServiceProvider):
    NAME: str = 'google'
    CLIENT_ID: str = os.getenv('GOOGLE_CLIENT_ID')
    CLIENT_SECRET: str = os.getenv('GOOGLE_CLIENT_SECRET')
    REDIRECT_URI: str = 'gdrive-authorization-success'
    REDIRECT_URL: str = f'{HOST_URL}/{REDIRECT_URI}'
    SCOPES: list = ['https://www.googleapis.com/auth/drive.metadata.readonly',
                    'https://www.googleapis.com/auth/drive.readonly']
    AUTH_URL: str = 'https://accounts.google.com/o/oauth2/v2/auth'
    TOKEN_URL: str = 'https://www.googleapis.com/oauth2/v4/token'
    REFRESH_URL: str = 'https://www.googleapis.com/oauth2/v4/token'

    @staticmethod
    async def search(search_term: str, client: httpx.AsyncClient, api_url: str, headers: dict, **kwargs) -> list:

        # corpora should be not sent if the user does not belong to any enterprise domain.
        gdrive_params = {
            'q': f'fullText contains "{search_term}"'
        }
        gdrive_response: httpx.Response = await client.get(url=api_url, params=gdrive_params, headers=headers)
        print("GDrive response is: " + str(gdrive_response.json()))
        gdrive_response_list = gdrive_response.json()['files']
        search_results = []
        for result in gdrive_response_list:
            search_results.append({
                'title': result.get('name'),
                'type': result.get('mimeType')
            })
        return search_results


class AtlassianServiceProvider(BaseServiceProvider):
    NAME: str = 'atlassian'
    CLIENT_ID: str = os.getenv('ATLASSIAN_CLIENT_ID')
    CLIENT_SECRET: str = os.getenv('ATLASSIAN_CLIENT_SECRET')
    REDIRECT_URI = 'atlassian-authorization-success'
    REDIRECT_URL: str = f'{HOST_URL}/{REDIRECT_URI}'
    SCOPES: list = ['read:confluence-content.all', 'read:confluence-content.summary', 'search:confluence',
                    'offline_access']
    AUTH_URL: str = 'https://auth.atlassian.com/authorize'
    TOKEN_URL: str = 'https://auth.atlassian.com/oauth/token'
    REFRESH_URL: str = 'https://auth.atlassian.com/oauth/token'

    @staticmethod
    async def search(search_term: str, client: httpx.AsyncClient, api_url: str, headers: dict,  **kwargs) -> list:
        query = f'text~{search_term}'
        confluence_response = await client.get(
            url=f"{api_url}/{kwargs.get('confluence_cloud_id')}/wiki/rest/api/search",
            params={
                'cql': query
            }, headers=headers)

        confluence_results: list = confluence_response.json()['results']

        search_results = []
        for result in confluence_results:
            search_results.append({
                        'excerpt': result['excerpt'],
                        'title': result['title'],
                        'link': result['url']
                    })
            print(result)
        return search_results


class SlackServiceProvider(BaseServiceProvider):
    NAME: str = 'slack'
    CLIENT_ID: str = os.getenv('SLACK_CLIENT_ID')
    CLIENT_SECRET: str = os.getenv('SLACK_CLIENT_SECRET')
    REDIRECT_URI = 'slack-authorization-success'
    REDIRECT_URL: str = f'{HOST_URL}/{REDIRECT_URI}'
    SCOPES: str = None
    USER_SCOPES: str = 'search:read'
    AUTH_URL: str = 'https://slack.com/oauth/v2/authorize'
    TOKEN_URL: str = 'https://slack.com/api/oauth.v2.access'
    REFRESH_URL: str = 'https://slack.com/api/oauth.v2.access'

    @staticmethod
    async def search(search_term: str, client: httpx.AsyncClient, api_url: str, headers: dict, **kwargs) -> list:
        slack_response = await client.get(url=f"{api_url}", params={
            'query': search_term
        }, headers=headers)
        print("slack response is: " + str(slack_response.json()))
        slack_results: list = slack_response.json()['messages']['matches']
        search_results = []
        for result in slack_results:
            search_results.append({
                'username': result.get('username'),
                'text': result.get('text'),
                'link': result.get('permalink')
            })
        return search_results

    @staticmethod
    def fix_access_token(params: dict) -> dict:
        access_token = params.get('authed_user')
        access_token['token_type'] = 'Bearer'
        return access_token
