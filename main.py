import flask
import os
import requests
import threading
import google_auth_oauthlib.flow
import google.oauth2.credentials
import googleapiclient.discovery
import oauthlib.oauth2.rfc6749.errors

from gphotosbackup import models, utils
from gphotosbackup import GPhotosBackup

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid',
          'https://www.googleapis.com/auth/photoslibrary.readonly',
          'https://www.googleapis.com/auth/userinfo.email']


app = flask.Flask(__name__)
app.secret_key = 'NOT REALLY NEEDED FOR LOCAL USAGE!'
db = models.DB()
global_crawler_lock = threading.Event()

@app.route("/")
def index():
    warning = None
    if 'warning' in flask.session:
        warning = flask.session['warning']
        del flask.session['warning']
    if not flask.session.get('user_id'):
        return flask.render_template('login.html', warning=warning)
    if not flask.session.get('credentials', {}):
        return flask.render_template('login.html', warning=warning)
    user_record = db.get_user_by(id=flask.session['user_id'])
    if not user_record:
        del flask.session['user_id']
        del flask.session['credentials']
        return flask.render_template('login.html', warning='User not found.')
    email = None
    if user_record:
        email = user_record.email
    
    return flask.render_template('index.html', email=email, warning=warning)


@app.route("/run")
def run():
    if not flask.session.get('user_id') or not flask.session.get('credentials', {}):
        return 'Authorization required.'
    credentials = google.oauth2.credentials.Credentials(
        **flask.session['credentials'])

    @flask.copy_current_request_context
    def update_credentials():
        flask.session['credentials'] = utils.credentials_to_dict(credentials)
    
    gphotos_backup = GPhotosBackup(global_crawler_lock=global_crawler_lock,
                                   user_id=flask.session['user_id'],
                                   credentials=credentials,
                                   update_credentials_callback=update_credentials,
                                   db=db)

    return flask.Response(gphotos_backup.run(),
                          content_type='text/event-stream')


@app.route("/create-client-secret-json")
def create_client_secret_json():
    """Explain how to create client_secret.json."""
    return flask.render_template('create-client-secret-json.html',
                                 filepath=os.path.abspath(CLIENT_SECRETS_FILE))


@app.route("/revoke")
def revoke():
    """Revoke credentials."""
    if 'credentials' not in flask.session:
        return flask.redirect(flask.url_for('index'))

    credentials = google.oauth2.credentials.Credentials(
        **flask.session['credentials'])
    requests.post('https://oauth2.googleapis.com/revoke',
        params={'token': credentials.token},
        headers = {'content-type': 'application/x-www-form-urlencoded'})

    if 'credentials' in flask.session:
        del flask.session['credentials']
    if 'user_id' in flask.session:
        del flask.session['user_id']

    return flask.redirect(flask.url_for('index'))


@app.route('/authorize')
def authorize():
    """Authorize within Google Account."""
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = flask.url_for('callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    flask.session['state'] = state
    return flask.redirect(authorization_url)


@app.route('/callback')
def callback():
    """Callback for Google Account authorization."""
    state = flask.session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = flask.url_for('callback', _external=True)

    authorization_response = flask.request.url
    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Warning:
        flask.session['warning'] = 'Make sure that you granted access to Google Photos.'
        return flask.redirect(flask.url_for('index'))
    except oauthlib.oauth2.rfc6749.errors.AccessDeniedError:
        flask.session['warning'] = 'Make sure that you granted access to Google Photos.'
        return flask.redirect(flask.url_for('index'))

    user_resource = googleapiclient.discovery.build(
        'oauth2', 'v2', credentials=flow.credentials, static_discovery=False)
    userinfo = user_resource.userinfo().get().execute()
    user_record = db.get_user_by(email=userinfo['email'])
    if user_record:
        user_id = user_record.id
    else:
        user_id = db.add_user(uid=userinfo['id'], email=userinfo['email'],
                              image_url=userinfo['picture'])
    flask.session['user_id'] = user_id
    flask.session['credentials'] = utils.credentials_to_dict(flow.credentials)
    return flask.redirect(flask.url_for('index'))


if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(host='localhost', port=8080, debug=True)
