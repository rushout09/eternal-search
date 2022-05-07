import asyncio
import uvloop
import uvicorn
import httpx
import redis
from random import SystemRandom
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from httpx_oauth.oauth2 import OAuth2
from oauthlib.common import UNICODE_ASCII_CHARACTER_SET
from starlette.datastructures import ImmutableMultiDict
from ServiceProviders import AtlassianServiceProvider, GoogleServiceProvider, SlackServiceProvider

app = FastAPI()
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
httpxClient = httpx.AsyncClient()
store = redis.Redis()

CONFLUENCE_API_URL = 'https://api.atlassian.com/ex/confluence'
oauth_atlassian: Optional[OAuth2] = None

GDRIVE_API_URL = 'https://www.googleapis.com/drive/v3/files'
oauth_google: Optional[OAuth2] = None

SLACK_API_URL = 'https://slack.com/api/search.all'
oauth_slack: Optional[OAuth2] = None


# currently this app is user agnostic. we will have to make it in such a way that user sign into or platform,
# he will get buttons to authorize all other apps. but they will authorize only for that particular user by default.
# currently we assume that user is already signed in.
#
# Todo: Research how option to refresh token works
# Todo: Improve 'state' design as mentioned in requests_oauthlib
# Todo: Research how to persist user tokens. p0
# Todo: Research how to refresh user tokens. p0
# Todo: Research way to invalidate token.
# Todo: Research way to show token status.
# Todo: Add Gmail search.
# Todo: Add Jira search.
# Todo: Add Github search.
# Todo: Sort search results according to relevance.
# Todo: beautify search results. p0
# Todo: Google Docs search add condition check for 'domain' user. p0
# Todo: Handle exception in search results.


@app.get('/')
@app.get('/home')
def home():
    html_content = """<form action="authorize-atlassian">
  <button type="submit">Authorize Confluence</button>
</form>
<form action="authorize-google">
  <button type="submit">Authorize Google Drive</button>
</form>
<form action="authorize-slack">
  <button type="submit">Authorize Slack</button>
</form>
<a href="https://slack.com/oauth/v2/authorize?client_id=3177588922981.3399496898834&scope=commands&user_scope=search:read"><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a>
<form action="search" method="POST">
    <input type="text" placeholder="Search.." name="text">
  <button type="submit">Search</button>
</form>"""
    return HTMLResponse(content=html_content, status_code=200)


@app.get('/authorize-atlassian')
async def authorize_atlassian():
    global oauth_atlassian
    oauth_atlassian = OAuth2(
        name=AtlassianServiceProvider.NAME,
        client_id=AtlassianServiceProvider.CLIENT_ID,
        client_secret=AtlassianServiceProvider.CLIENT_SECRET,
        authorize_endpoint=AtlassianServiceProvider.AUTH_URL,
        access_token_endpoint=AtlassianServiceProvider.TOKEN_URL,
        refresh_token_endpoint=AtlassianServiceProvider.REFRESH_URL,
        base_scopes=AtlassianServiceProvider.SCOPES)
    authorization_url = await oauth_atlassian.get_authorization_url(redirect_uri=AtlassianServiceProvider.REDIRECT_URL,
                                                                    state=generate_token(),
                                                                    extras_params={'prompt': 'consent',
                                                                                   'audience': 'api.atlassian.com'})
    return RedirectResponse(authorization_url)


@app.get('/authorize-google')
async def authorize_google():
    global oauth_google
    oauth_google = OAuth2(
        name=GoogleServiceProvider.NAME,
        client_id=GoogleServiceProvider.CLIENT_ID,
        client_secret=GoogleServiceProvider.CLIENT_SECRET,
        authorize_endpoint=GoogleServiceProvider.AUTH_URL,
        access_token_endpoint=GoogleServiceProvider.TOKEN_URL,
        refresh_token_endpoint=GoogleServiceProvider.REFRESH_URL,
        base_scopes=GoogleServiceProvider.SCOPES)
    authorization_url = await oauth_google.get_authorization_url(redirect_uri=GoogleServiceProvider.REDIRECT_URL,
                                                                 state=generate_token(),
                                                                 extras_params={'prompt': 'consent',
                                                                                'access_type': 'offline'})
    return RedirectResponse(authorization_url)


@app.get('/authorize-slack')
async def authorize_slack():
    global oauth_slack
    oauth_slack = OAuth2(
        name=SlackServiceProvider.NAME,
        client_id=SlackServiceProvider.CLIENT_ID,
        client_secret=SlackServiceProvider.CLIENT_SECRET,
        authorize_endpoint=SlackServiceProvider.AUTH_URL,
        access_token_endpoint=SlackServiceProvider.TOKEN_URL,
        refresh_token_endpoint=SlackServiceProvider.REFRESH_URL)
    authorization_url = await oauth_slack.get_authorization_url(redirect_uri=SlackServiceProvider.REDIRECT_URL,
                                                                state=generate_token(),
                                                                extras_params={
                                                                    'user_scope': SlackServiceProvider.USER_SCOPES})
    return RedirectResponse(authorization_url)


@app.get(f'/{GoogleServiceProvider.REDIRECT_URI}')
async def google_authorization_success(code: str):

    oauth2_token = await oauth_google.get_access_token(code=code, redirect_uri=GoogleServiceProvider.REDIRECT_URL)

    google_access_token = oauth2_token.get('access_token')
    google_refresh_token = oauth2_token.get('refresh_token')

    store.hset("GOOGLE", "ACCESS", google_access_token)
    store.hset("GOOGLE", "REFRESH", google_access_token)

    print(google_refresh_token)
    print(google_access_token)
    return RedirectResponse('/home')


@app.get(f'/{SlackServiceProvider.REDIRECT_URI}')
async def slack_authorization_success(code: str):

    improper_oauth2_token = await oauth_slack.get_access_token(code=code,
                                                               redirect_uri=SlackServiceProvider.REDIRECT_URL)

    oauth2_token = SlackServiceProvider.fix_access_token(improper_oauth2_token)

    slack_access_token = oauth2_token.get('access_token')
    slack_refresh_token = oauth2_token.get('refresh_token')

    store.hset("SLACK", "ACCESS", slack_access_token)
    store.hset("SLACK", "REFRESH", slack_refresh_token)

    print(slack_refresh_token)
    print(slack_access_token)
    return RedirectResponse('/home')


@app.get(f'/{AtlassianServiceProvider.REDIRECT_URI}')
async def atlassian_authorization_success(code: str):

    oauth2_token = await oauth_atlassian.get_access_token(code=code, redirect_uri=AtlassianServiceProvider.REDIRECT_URL)

    atlassian_access_token = oauth2_token.get('access_token')
    atlassian_refresh_token = oauth2_token.get('refresh_token')

    response: httpx.Response = await httpxClient.get(url='https://api.atlassian.com/oauth/token/accessible-resources',
                                                     headers={'Authorization': f"Bearer {atlassian_access_token}",
                                                              'Accept': 'application/json'})
    confluence_cloud_id = response.json()[0]['id']

    store.hset("ATLASSIAN", "ACCESS", atlassian_access_token)
    store.hset("ATLASSIAN", "REFRESH", atlassian_refresh_token)
    store.hset("ATLASSIAN", "CLOUD_ID", confluence_cloud_id)

    return RedirectResponse('/home')


@app.post('/search')
async def search(request: Request):
    request_form: ImmutableMultiDict = await request.form()
    text = request_form.get("text")

    response_url = request_form.get('response_url')

    print(f'text = {text}')
    print(f'response_url = {response_url}')

    asyncio.create_task(search_worker(text=text, response_url=response_url))

    response = {
        "response_type": "in_channel",
        "text": "Searching Eternity."
    }

    return response


async def search_worker(text: str, response_url: str):

    print('inside search worker')

    complete_search_result = []

    if oauth_slack:
        slack_access_token = store.hget('SLACK', 'ACCESS')
        headers = {'Authorization': f"Bearer {slack_access_token}",
                   'Accept': 'application/json'}
        slack_search_results = await SlackServiceProvider.search(search_term=text, client=httpxClient,
                                                                 api_url=SLACK_API_URL, headers=headers)
        complete_search_result.append(slack_search_results)
    if oauth_google:
        google_access_token = store.hget('GOOGLE', 'ACCESS')
        headers = {'Authorization': f"Bearer {google_access_token}",
                   'Accept': 'application/json'}
        gdrive_search_results = await GoogleServiceProvider.search(search_term=text, client=httpxClient,
                                                                   api_url=GDRIVE_API_URL, headers=headers)
        complete_search_result.append(gdrive_search_results)
    if oauth_atlassian:
        atlassian_access_token = store.hget('ATLASSIAN', 'ACCESS')
        confluence_cloud_id = store.hget('ATLASSIAN', 'CLOUD_ID')
        headers = {'Authorization': f"Bearer {atlassian_access_token}",
                   'Accept': 'application/json'}
        confluence_search_results = await AtlassianServiceProvider.search(search_term=text, client=httpxClient,
                                                                          api_url=CONFLUENCE_API_URL, headers=headers,
                                                                          confluence_cloud_id=confluence_cloud_id)
        complete_search_result.append(confluence_search_results)

    print(f'Complete search results: {str(complete_search_result)}')

    response = await httpxClient.post(url=response_url, json={"text": str(complete_search_result),
                                                              "response_type": "in_channel"})

    print(f'post response status {response.status_code} and content {response.content}')

    return


def generate_token(length=30, chars=UNICODE_ASCII_CHARACTER_SET):
    """Generates a non-guessable OAuth token

    OAuth (1 and 2) does not specify the format of tokens except that they
    should be strings of random characters. Tokens should not be guessable
    and entropy when generating the random characters is important. Which is
    why SystemRandom is used instead of the default random.choice method.
    """
    rand = SystemRandom()
    return ''.join(rand.choice(chars) for x in range(length))


if __name__ == '__main__':
    uvicorn.run(app='main:app', port=9000)
