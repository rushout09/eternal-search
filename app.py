from flask import Flask, request, redirect
import requests
from requests import Response
from requests_oauthlib import OAuth2Session

from ServiceProviders import AtlassianServiceProvider, GoogleServiceProvider, SlackServiceProvider

app = Flask(__name__)

CONFLUENCE_API_URL = 'https://api.atlassian.com/ex/confluence'
oauth_atlassian: OAuth2Session = None
ATLASSIAN_ACCESS_TOKEN: str
ATLASSIAN_REFRESH_TOKEN: str
CONFLUENCE_CLOUD_ID: str

GDRIVE_API_URL = 'https://www.googleapis.com/drive/v3/files'
oauth_google: OAuth2Session = None
GOOGLE_ACCESS_TOKEN: str
GOOGLE_REFRESH_TOKEN: str

SLACK_API_URL = 'https://slack.com/api/search.all'
oauth_slack: OAuth2Session = None
SLACK_ACCESS_TOKEN: str
SLACK_REFRESH_TOKEN: str

# currently this app is user agnostic. we will have to make it in such a way that user sign into or platform,
# he will get buttons to authorize all other apps. but they will authorize only for that particular user by default.
# currently we assume that user is already signed in.
#
# Todo: Research how option to refresh token works
# Todo: Improve 'state' design as mentioned in requests_oauthlib
# Todo: Research how to save user tokens.
# Todo: Research way to invalidate token.
# Todo: Research way to show token status.
# Todo: Google Docs search add condition check for 'domain' user.
# Todo: Add Gmail search.
# Todo: Add Jira search.
# Todo: Add Github search.
# Todo: Sort search results according to relevance.
# Todo: Research how to save client credentials. p0
# Todo: push to github. p0
# Todo: async api calls. p0
# Todo: beautify search results. p0


@app.route('/')
@app.route('/home')
def home():
    return """<form action="authorize-atlassian">
  <button type="submit">Authorize Confluence</button>
</form>
<form action="authorize-google">
  <button type="submit">Authorize Google Drive</button>
</form>
<form action="authorize-slack">
  <button type="submit">Authorize Slack</button>
</form>
<a href="https://slack.com/oauth/v2/authorize?client_id=3177588922981.3399496898834&scope=commands&user_scope=search:read"><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a>
<form action="search">
    <input type="text" placeholder="Search.." name="search">
  <button type="submit">Search</button>
</form>"""


@app.route('/slack')
def slack():
    args = request.args.to_dict()
    return args


@app.route('/authorize-atlassian')
def authorize_atlassian():
    global oauth_atlassian
    oauth_atlassian = OAuth2Session(client_id=AtlassianServiceProvider.CLIENT_ID,
                                    scope=AtlassianServiceProvider.SCOPES,
                                    auto_refresh_url=AtlassianServiceProvider.TOKEN_URL,
                                    redirect_uri=AtlassianServiceProvider.REDIRECT_URL)
    authorization_url, state = oauth_atlassian.authorization_url(url=AtlassianServiceProvider.AUTH_URL,
                                                                 prompt='consent')
    return redirect(authorization_url)


@app.route('/authorize-google')
def authorize_google():
    global oauth_google
    oauth_google = OAuth2Session(client_id=GoogleServiceProvider.CLIENT_ID,
                                 scope=GoogleServiceProvider.SCOPES,
                                 auto_refresh_url=GoogleServiceProvider.TOKEN_URL,
                                 redirect_uri=GoogleServiceProvider.REDIRECT_URL)
    authorization_url, state = oauth_google.authorization_url(url=GoogleServiceProvider.AUTH_URL, access_type='offline',
                                                              prompt='select_account')
    return redirect(authorization_url)


@app.route('/authorize-slack')
def authorize_slack():
    global oauth_slack
    oauth_slack = OAuth2Session(client_id=SlackServiceProvider.CLIENT_ID,
                                auto_refresh_url=SlackServiceProvider.TOKEN_URL,
                                redirect_uri=SlackServiceProvider.REDIRECT_URL,
                                scope=None)
    authorization_url, state = oauth_slack.authorization_url(url=SlackServiceProvider.AUTH_URL,
                                                             user_scope=SlackServiceProvider.USER_SCOPES)
    return redirect(authorization_url)


@app.route(f'/{GoogleServiceProvider.REDIRECT_URI}')
def google_authorization_success():
    global GOOGLE_ACCESS_TOKEN, GOOGLE_REFRESH_TOKEN
    args = request.args.to_dict()
    oauth2_token = oauth_google.fetch_token(token_url=GoogleServiceProvider.TOKEN_URL,
                                            client_secret=GoogleServiceProvider.CLIENT_SECRET,
                                            include_client_id=True,
                                            code=args.get('code'))

    GOOGLE_ACCESS_TOKEN = oauth2_token.get('access_token')
    GOOGLE_REFRESH_TOKEN = oauth2_token.get('refresh_token')

    print(GOOGLE_REFRESH_TOKEN)
    print(GOOGLE_ACCESS_TOKEN)
    return redirect('/home')


@app.route(f'/{SlackServiceProvider.REDIRECT_URI}')
def slack_authorization_success():
    global SLACK_ACCESS_TOKEN, SLACK_REFRESH_TOKEN
    args = request.args.to_dict()
    oauth_slack.register_compliance_hook('access_token_response', SlackServiceProvider.fix_access_token)
    oauth2_token = oauth_slack.fetch_token(token_url=SlackServiceProvider.TOKEN_URL,
                                           client_secret=SlackServiceProvider.CLIENT_SECRET,
                                           include_client_id=True,
                                           code=args.get('code'))

    SLACK_ACCESS_TOKEN = oauth2_token.get('access_token')
    SLACK_REFRESH_TOKEN = oauth2_token.get('refresh_token')

    print(SLACK_REFRESH_TOKEN)
    print(SLACK_ACCESS_TOKEN)
    return redirect('/home')


@app.route(f'/{AtlassianServiceProvider.REDIRECT_URI}')
def atlassian_authorization_success():
    global ATLASSIAN_ACCESS_TOKEN, ATLASSIAN_REFRESH_TOKEN, CONFLUENCE_CLOUD_ID
    args = request.args.to_dict()
    oauth2_token = oauth_atlassian.fetch_token(token_url=AtlassianServiceProvider.TOKEN_URL,
                                               client_secret=AtlassianServiceProvider.CLIENT_SECRET,
                                               include_client_id=True,
                                               code=args.get('code'))

    ATLASSIAN_ACCESS_TOKEN = oauth2_token.get('access_token')
    ATLASSIAN_REFRESH_TOKEN = oauth2_token.get('refresh_token')

    response: Response = requests.get(url='https://api.atlassian.com/oauth/token/accessible-resources',
                                      headers={'Authorization': f"Bearer {ATLASSIAN_ACCESS_TOKEN}",
                                               'Accept': 'application/json'})
    response_json = response.json()
    print(response_json)
    cloud_id = response_json[0]['id']
    CONFLUENCE_CLOUD_ID = cloud_id
    return redirect('/home')

#
# @app.route('/search')
# def search():
#     return 'true'


@app.route('/search', methods=['POST', 'GET'])
def search():

    if request.method == 'GET':
        args = request.args.to_dict()
        search_term = args.get('search')
    else:
        form = request.form.to_dict()
        search_term = form.get('text')

    complete_search_result = []

    if oauth_slack:
        slack_search_results = SlackServiceProvider.search(search_term=search_term, oauth=oauth_slack,
                                                           api_url=SLACK_API_URL)
        complete_search_result.append(slack_search_results)
    if oauth_google:
        gdrive_search_results = GoogleServiceProvider.search(search_term=search_term, oauth=oauth_google,
                                                             api_url=GDRIVE_API_URL)
        complete_search_result.append(gdrive_search_results)
    if oauth_atlassian:
        confluence_search_results = AtlassianServiceProvider.search(search_term=search_term, oauth=oauth_atlassian,
                                                                    api_url=CONFLUENCE_API_URL,
                                                                    confluence_cloud_id=CONFLUENCE_CLOUD_ID)
        complete_search_result.append(confluence_search_results)

    return str(complete_search_result)


if __name__ == '__main__':
    app.run(debug=False, port=9000)
