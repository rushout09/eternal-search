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

# HOST_URL: str = 'https://rushabh.loca.lt'
HOST_URL = os.getenv('HOST_URL')

KEY = os.getenv('KEY')
cipher = Fernet(KEY.encode("utf-8"))

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
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
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
        if refresh_token is not None:
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
    SCOPES: list = ['https://www.googleapis.com/auth/drive.readonly', 'https://www.googleapis.com/auth/gmail.readonly']
    AUTH_URL: str = 'https://accounts.google.com/o/oauth2/v2/auth'
    TOKEN_URL: str = 'https://www.googleapis.com/oauth2/v4/token'
    REFRESH_URL: str = 'https://www.googleapis.com/oauth2/v4/token'
    GDRIVE_API_URL: str = 'https://www.googleapis.com/drive/v3/files'
    GMAIL_API_URL: str = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'

    oauth: OAuth2 = OAuth2(
        name=NAME,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint=AUTH_URL,
        access_token_endpoint=TOKEN_URL,
        refresh_token_endpoint=REFRESH_URL,
        base_scopes=SCOPES)

    @classmethod
    async def get_mail(cls, message_id: str, access_token: str):

        params = {
            'format': 'minimal'
        }
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:
            async with httpx.AsyncClient() as client:
                while retry:
                    response: httpx.Response = await client.get(url=f"{cls.GMAIL_API_URL}/{message_id}",
                                                                headers=headers,
                                                                timeout=timeout, params=params)
                    if response.status_code == 200:
                        retry = False
                    elif response.status_code == 401:
                        await cls.refresh_token()
                    else:
                        raise ValueError("Invalid Response")
            return response.json()['snippet']
        except ValueError:
            print(str(ValueError))
            return ""

    @classmethod
    async def gmail_search(cls, search_term: str, access_token: str, **kwargs) -> list:
        gmail_params = {
            'q': f'{search_term}'
        }

        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:

            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(url=cls.GMAIL_API_URL, params=gmail_params,
                                                                headers=headers,
                                                                timeout=timeout)
                    if response.status_code == 200:
                        retry = False
                    elif response.status_code == 401:
                        await cls.refresh_token()
                    else:
                        raise ValueError("Invalid Response")

            print("GMail response is: " + str(response.json()))
            gmail_response_list = response.json()['messages'][:5]
            search_results = []
            for result in gmail_response_list:
                mail_result = await cls.get_mail(message_id=result.get('id'), access_token=access_token)
                search_results.append({
                    'title': mail_result,
                    'id': result.get('id')
                })
            return search_results
        except ValueError:
            print(str(ValueError))
            return []

    @classmethod
    async def gdrive_search(cls, search_term: str, access_token: str, **kwargs) -> list:
        # corpora should be not sent if the user does not belong to any enterprise domain.
        gdrive_params = {
            'q': f'fullText contains "{search_term}"',
            'corpora': 'user',
            'fields': 'files(name, webViewLink, id)'
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
                    'link': result.get('webViewLink'),
                    'id': result.get('id')
                })
            return search_results[:5]
        except ValueError:
            print(str(ValueError))
            return []

    @classmethod
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
        google_results: list = []
        gmail_results: list = await cls.gmail_search(search_term=search_term, access_token=access_token, **kwargs)
        gdrive_results: list = await cls.gdrive_search(search_term=search_term, access_token=access_token, **kwargs)
        google_results.extend(gmail_results)
        google_results.extend(gdrive_results)
        return google_results


class AtlassianServiceProvider(BaseServiceProvider):
    NAME: str = 'atlassian'
    CLIENT_ID: str = os.getenv('ATLASSIAN_CLIENT_ID')
    CLIENT_SECRET: str = os.getenv('ATLASSIAN_CLIENT_SECRET')
    REDIRECT_URI = 'atlassian-authorization-success'
    REDIRECT_URL: str = f'{HOST_URL}/{REDIRECT_URI}'
    SCOPES: list = ['read:content-details:confluence',
                    'read:issue-details:jira', 'read:audit-log:jira', 'read:avatar:jira',
                    'read:field-configuration:jira', 'read:issue-meta:jira', 'offline_access']
    AUTH_URL: str = 'https://auth.atlassian.com/authorize'
    TOKEN_URL: str = 'https://auth.atlassian.com/oauth/token'
    REFRESH_URL: str = 'https://auth.atlassian.com/oauth/token'
    CONFLUENCE_API_URL: str = 'https://api.atlassian.com/ex/confluence'
    JIRA_API_URL: str = 'https://api.atlassian.com/ex/jira'

    oauth: OAuth2 = OAuth2(
        name=NAME,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint=AUTH_URL,
        access_token_endpoint=TOKEN_URL,
        refresh_token_endpoint=REFRESH_URL,
        base_scopes=SCOPES)

    @classmethod
    async def jira_search(cls, search_term: str, access_token: str, **kwargs):
        query = f'text~"{search_term}"'
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:
            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(
                        url=f"{cls.JIRA_API_URL}/{kwargs.get('cloud_id')}/rest/api/3/search",
                        params={
                            'jql': query
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

            jira_results: list = response.json()['issues']
            print("Jira response is: " + str(jira_results))
            search_results = []
            for result in jira_results:

                link = store.hget("ATLASSIAN", "CLOUD_URL").decode("utf-8") + "/browse/" + result['key']
                title = result['key'] + " " + result['fields']['summary']
                print(link)
                search_results.append({
                    'title': title,
                    'link': link,
                    'id': result['id']
                })
                print(result)
            return search_results

        except ValueError:
            print(str(ValueError))
            return []

    @classmethod
    async def confluence_search(cls, search_term: str, access_token: str, **kwargs) -> list:
        query = f'text~"{search_term}"'
        headers = {'Authorization': f"Bearer {access_token}",
                   'Accept': 'application/json'}

        retry = True

        try:
            async with httpx.AsyncClient() as client:

                while retry:
                    response: httpx.Response = await client.get(
                        url=f"{cls.CONFLUENCE_API_URL}/{kwargs.get('cloud_id')}/wiki/rest/api/search",
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
                link = store.hget("ATLASSIAN", "CLOUD_URL").decode("utf-8") + result['content']['_links'].get('webui')
                title = result['content']['title']
                excerpt = result['excerpt'].replace("@@@hl@@@", "")
                excerpt = excerpt.replace("@@@endhl@@@", "")
                print(link)
                search_results.append({
                    'excerpt': excerpt,
                    'title': title,
                    'link': link,
                    'id': result['content']['id'],
                    'score': result.get('score', 0)
                })
                print(result)
            return search_results

        except ValueError:
            print(str(ValueError))
            return []

    @classmethod
    async def search(cls, search_term: str, access_token: str, **kwargs) -> list:
        atlassian_results: list = []
        jira_results: list = await cls.jira_search(search_term=search_term, access_token=access_token, **kwargs)
        confluence_results: list = await cls.confluence_search(search_term=search_term,
                                                               access_token=access_token, **kwargs)
        atlassian_results.extend(confluence_results[:5])
        atlassian_results.extend(jira_results[:5])
        return atlassian_results


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
                                                                params={'query': search_term, 'highlight': False},
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
                if 'coade search' not in result.get('username'):
                    search_results.append({
                        'username': result.get('username'),
                        'text': result.get('text'),
                        'link': result.get('permalink'),
                        'id': result.get('iid'),
                        'score': result.get('score')
                    })
            return search_results[:5]

        except ValueError:
            print(str(ValueError))
            return []

    @staticmethod
    def fix_access_token(params: dict) -> dict:
        access_token = params.get('authed_user')
        access_token['token_type'] = 'Bearer'
        return access_token
