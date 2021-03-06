import asyncio
import uvloop
import uvicorn
import httpx
import redis
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import ImmutableMultiDict
from ServiceProviders import AtlassianServiceProvider, GoogleServiceProvider, SlackServiceProvider

app = FastAPI()
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
httpxClient = httpx.AsyncClient()
store = redis.Redis()


# currently, this app is user agnostic. we will have to make it in such a way that user sign into or platform,
# he will get buttons to authorize all other apps. but they will authorize only for that particular user by default.
# currently, we assume that user is already signed in.

# Todo: Improve 'state' design as mentioned in requests_oauthlib to improve security. p2
# Todo: Research way to invalidate token and show token status. p2
# Todo: Possible sources to add: MS Outlook, Teams, onedrive, intercom, CRMs, Github search. p2
# Todo: Implement user sign in and session management. p0
# Todo: Add unit tests. p1
# Todo: Return formatted and relevant search results. p0
# Todo: figure out how to add the app to slack. p0
# Todo: handle gmail no response error. p0


@app.get('/')
@app.get('/home')
def home():
    html_content = """<form action="authorize-atlassian"> <button type="submit">Authorize Atlassian</button> </form> 
    <form action="authorize-google"> <button type="submit">Authorize Google</button> </form> <form 
    action="authorize-slack"> <button type="submit">Authorize Slack</button> </form> <a 
    href="https://slack.com/oauth/v2/authorize?client_id=3177588922981.3399496898834&scope=commands&user_scope=search
    :read"><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" 
    srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, 
    https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a> <form action="search" method="POST"> <input 
    type="text" placeholder="Search.." name="text"> <button type="submit">Search</button> </form> """
    return HTMLResponse(content=html_content, status_code=200)


@app.get('/authorize-atlassian')
async def authorize_atlassian():
    authorization_url = await AtlassianServiceProvider.get_authorization_url(
        extras_params={'prompt': 'consent',
                       'audience': 'api.atlassian.com'})
    return RedirectResponse(authorization_url)


@app.get('/authorize-google')
async def authorize_google():
    authorization_url = await GoogleServiceProvider.get_authorization_url(
        extras_params={'prompt': 'consent',
                       'access_type': 'offline'})
    return RedirectResponse(authorization_url)


@app.get('/authorize-slack')
async def authorize_slack():
    authorization_url = await SlackServiceProvider.get_authorization_url(
        extras_params={
            'user_scope': SlackServiceProvider.USER_SCOPES})
    return RedirectResponse(authorization_url)


@app.get(f'/{GoogleServiceProvider.REDIRECT_URI}')
async def google_authorization_success(code: str):
    oauth2_token = await GoogleServiceProvider.get_initial_oauth_token(code=code)
    GoogleServiceProvider.persist_oauth_token(oauth2_token=oauth2_token)
    return RedirectResponse('/home')


@app.get(f'/{SlackServiceProvider.REDIRECT_URI}')
async def slack_authorization_success(code: str):
    oauth2_token = await SlackServiceProvider.get_initial_oauth_token(code=code)
    oauth2_token = SlackServiceProvider.fix_access_token(oauth2_token)
    SlackServiceProvider.persist_oauth_token(oauth2_token=oauth2_token)
    return RedirectResponse('/home')


@app.get(f'/{AtlassianServiceProvider.REDIRECT_URI}')
async def atlassian_authorization_success(code: str):
    oauth2_token = await AtlassianServiceProvider.get_initial_oauth_token(code=code)

    atlassian_access_token = oauth2_token.get('access_token')

    response: httpx.Response = await httpxClient.get(url='https://api.atlassian.com/oauth/token/accessible-resources',
                                                     headers={'Authorization': f"Bearer {atlassian_access_token}",
                                                              'Accept': 'application/json'})
    atlassian_cloud_id = response.json()[0]['id']
    atlassian_cloud_url = response.json()[0]['url']

    AtlassianServiceProvider.persist_oauth_token(oauth2_token=oauth2_token)
    store.hset("ATLASSIAN", "CLOUD_ID", str(atlassian_cloud_id))
    store.hset("ATLASSIAN", "CLOUD_URL", str(atlassian_cloud_url))

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
        "text": f"Searching Eternity for {text}."
    }

    return response


async def search_worker(text: str, response_url: str):
    print('inside search worker')

    complete_search_result = []

    slack_access_token = await SlackServiceProvider.get_access_token()
    if slack_access_token:
        slack_search_results = await SlackServiceProvider.search(search_term=text, access_token=slack_access_token)
        complete_search_result.extend(slack_search_results)

    google_access_token = await GoogleServiceProvider.get_access_token()
    if google_access_token:

        gdrive_search_results = await GoogleServiceProvider.search(search_term=text, access_token=google_access_token)
        complete_search_result.extend(gdrive_search_results)

    atlassian_access_token = await AtlassianServiceProvider.get_access_token()
    if atlassian_access_token:

        confluence_search_results = await AtlassianServiceProvider.search(search_term=text,
                                                                          access_token=atlassian_access_token,
                                                                          cloud_id=store.hget("ATLASSIAN", "CLOUD_ID")
                                                                          .decode("utf-8"))
        complete_search_result.extend(confluence_search_results)

    prepared_response = prepare_response(complete_search_result)
    print(f'Complete search results: {prepared_response}')

    response = await httpxClient.post(url=response_url, json={"text": prepared_response,
                                                              "response_type": "in_channel",
                                                              "type": "mrkdwn"}
                                      )

    print(f'post response status {response.status_code} and content {response.content}')

    return


def prepare_response(search_results: list):
    prepared_response = ""
    for result in search_results:
        if result.get('title') is not None:
            prepared_response = prepared_response + f"Title: *{result.get('title')}* \n"
        if result.get('username') is not None:
            prepared_response = prepared_response + f"From: *{result.get('username')}* \n"
        if result.get('text') is not None:
            prepared_response = prepared_response + f"{result.get('text')} \n"
        if result.get('excerpt') is not None:
            prepared_response = prepared_response + f"{result.get('excerpt')} \n"
        if result.get('link') is not None:
            prepared_response = prepared_response + f"link: {result.get('link')}"

        prepared_response = prepared_response + "\n\n\n"

    return prepared_response


if __name__ == '__main__':
    uvicorn.run(app='main:app', port=9000)
