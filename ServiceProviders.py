import httpx
import os
import redis
from dotenv import load_dotenv
from datetime import datetime, timezone
from httpx_oauth.oauth2 import OAuth2
from oauthlib.common import UNICODE_ASCII_CHARACTER_SET
from random import SystemRandom
from cryptography.fernet import Fernet

load_dotenv()
store = redis.Redis()
cipher = Fernet(Fernet.generate_key())

# HOST_URL: str = 'https://rushabh.loca.lt'
HOST_URL = os.getenv('HOST_URL')

timeout = httpx.Timeout(10.0)


class BaseServiceProvider:
    NAME: str
    CLIENT_ID: str
    CLIENT_SECRET: str
    REDIRECT_URI: str
    REDIRECT_URL: str
    SCOPES: str
    AUTH_URL: str
    TOKEN_URL: str
    REFRESH_URL: str
    oauth: OAuth2

    @classmethod
    async def search(cls, search_term: str, client: httpx.AsyncClient, api_url: str, headers: dict, **kwargs) -> list:
        raise NotImplementedError

    @classmethod
    async def get_access_token(cls):
        print(cls)
        print(cls.NAME)
        if store.hget(cls.NAME, 'ACCESS'):
            access_token = cipher.decrypt((store.hget(cls.NAME, 'ACCESS'))).decode("utf-8")
            expiry_time = int(store.hget(cls.NAME, 'EXPIRES_AT').decode("utf-8"))
            if expiry_time < int(round(datetime.now(tz=timezone.utc).timestamp())):
                await cls.refresh_token()

                access_token = cipher.decrypt((store.hget(cls.NAME, 'ACCESS'))).decode("utf-8")
            return access_token
        return None

    @classmethod
    def persist_oauth_token(cls, oauth2_token: dict):

        print(cls)
        print(cls.NAME)
        access_token = oauth2_token.get('access_token')
        refresh_token = oauth2_token.get('refresh_token')
        expires_at = oauth2_token.get('expires_in') + int(round(datetime.now(tz=timezone.utc).timestamp()))
        scopes = oauth2_token.get('scope')

        store.hset(cls.NAME, "ACCESS", cipher.encrypt(access_token.encode("utf-8")))
        store.hset(cls.NAME, "REFRESH", cipher.encrypt(refresh_token.encode("utf-8")))
        store.hset(cls.NAME, "EXPIRES_AT", str(expires_at))
        store.hset(cls.NAME, "SCOPES", scopes)

    @classmethod
    async def refresh_token(cls):

        print(cls)
        print(cls.NAME)
        refresh_token = cipher.decrypt((store.hget(cls.NAME, 'REFRESH'))).decode("utf-8")
        print("refreshing access token")
        oauth2_token = await cls.oauth.refresh_token(refresh_token=refresh_token)
        cls.persist_oauth_token(oauth2_token)

    @classmethod
    async def get_authorization_url(cls, extras_params: dict):

        return await cls.oauth.get_authorization_url(
            redirect_uri=cls.REDIRECT_URL,
            state=cls.generate_token(),
            extras_params=extras_params)

    @classmethod
    async def get_initial_oauth_token(cls, code):

        oauth2_token = await cls.oauth.get_access_token(code=code, redirect_uri=cls.REDIRECT_URL)
        return oauth2_token

    @classmethod
    def generate_token(cls, length=30, chars=UNICODE_ASCII_CHARACTER_SET):
        """Generates a non-guessable OAuth token

        OAuth (1 and 2) does not specify the format of tokens except that they
        should be strings of random characters. Tokens should not be guessable
        and entropy when generating the random characters is important. Which is
        why SystemRandom is used instead of the default random.choice method.
        """
        rand = SystemRandom()
        return ''.join(rand.choice(chars) for _ in range(length))


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
    GDRIVE_API_URL: str = 'https://www.googleapis.com/drive/v3/files'
    oauth: OAuth2 = OAuth2(
        name=NAME,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint=AUTH_URL,
        access_token_endpoint=TOKEN_URL,
        refresh_token_endpoint=REFRESH_URL,
        base_scopes=SCOPES)

    @classmethod
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
        # corpora should be not sent if the user does not belong to any enterprise domain.
        gdrive_params = {
            'q': f'fullText contains "{search_term}"',
            'corpora': 'domain'
        }
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:

            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(url=cls.GDRIVE_API_URL, params=gdrive_params,
                                                                headers=headers,
                                                                timeout=timeout)
                    if response.status_code == 200:
                        retry = False
                    elif response.status_code == 400:
                        gdrive_params = {
                            'q': f'fullText contains "{search_term}"'
                        }
                    elif response.status_code == 401:
                        await cls.refresh_token()
                    else:
                        raise ValueError("Invalid Response")

            print("GDrive response is: " + str(response.json()))
            gdrive_response_list = response.json()['files']
            search_results = []
            for result in gdrive_response_list:
                search_results.append({
                    'title': result.get('name'),
                    'type': result.get('mimeType')
                })
            return search_results
        except ValueError:
            print(str(ValueError))
            return []


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
    CONFLUENCE_API_URL: str = 'https://api.atlassian.com/ex/confluence'
    oauth: OAuth2 = OAuth2(
        name=NAME,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint=AUTH_URL,
        access_token_endpoint=TOKEN_URL,
        refresh_token_endpoint=REFRESH_URL,
        base_scopes=SCOPES)

    @classmethod
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
        query = f'text~{search_term}'
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:
            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(
                        url=f"{cls.CONFLUENCE_API_URL}/{kwargs.get('confluence_cloud_id')}/wiki/rest/api/search",
                        params={
                            'cql': query
                        },
                        headers=headers,
                        timeout=timeout)

                    # Confirm if status code for expired access token is correct.
                    if response.status_code == 200:
                        retry = False
                    elif response.status_code == 403:
                        await cls.refresh_token()
                    else:
                        raise ValueError("Invalid Response")

            confluence_results: list = response.json()['results']
            print("confluence response is: " + str(confluence_results))
            search_results = []
            for result in confluence_results:
                search_results.append({
                    'excerpt': result['excerpt'],
                    'title': result['title'],
                    'link': result['url']
                })
                print(result)
            return search_results

        except ValueError:
            print(str(ValueError))
            return []


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
    SLACK_API_URL: str = 'https://slack.com/api/search.all'
    oauth: OAuth2 = OAuth2(
        name=NAME,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint=AUTH_URL,
        access_token_endpoint=TOKEN_URL,
        refresh_token_endpoint=REFRESH_URL,
        base_scopes=SCOPES)

    @classmethod
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:
            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(url=f"{cls.SLACK_API_URL}",
                                                                params={'query': search_term},
                                                                headers=headers,
                                                                timeout=timeout)
                    print("slack response is: " + str(response.json()))
                    response_json = response.json()
                    if response_json['ok'] is True:
                        retry = False
                    elif response_json['ok'] is False and response_json['error'] == "invalid_auth":
                        await cls.refresh_token()
                    else:
                        raise ValueError("Invalid Response")

            slack_results: list = response.json()['messages']['matches']
            search_results = []
            for result in slack_results:
                search_results.append({
                    'username': result.get('username'),
                    'text': result.get('text'),
                    'link': result.get('permalink')
                })
            return search_results

        except ValueError:
            print(str(ValueError))
            return []

    @staticmethod
    def fix_access_token(params: dict) -> dict:
        access_token = params.get('authed_user')
        access_token['token_type'] = 'Bearer'
        return access_token
