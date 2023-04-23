import os
import flask

import requests

import google_auth_oauthlib.flow

from gphotobackup import GPhotoBackup

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'

backup = GPhotoBackup()
app = flask.Flask(__name__)
app.secret_key = 'NOT REALLY IMPORTANT FOR NOW!'

@app.route("/")
def index():
    if backup.check_credentials():
        return flask.redirect(flask.url_for('disable_credentials'))
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return flask.redirect(flask.url_for('create_client_secret_json'))
    try:
        google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES)
    except ValueError:
        return flask.redirect(flask.url_for('create_client_secret_json'))
    
    return flask.render_template("index.html")

@app.route("/create-client-secret-json")
def create_client_secret_json():
    """Explain how to create client_secret.json."""
    return flask.render_template("create-client-secret-json.html",
                                 filepath=os.path.abspath(CLIENT_SECRETS_FILE))

@app.route("/disable-credentials")
def disable_credentials():
    """Disable credentials."""
    if not backup.check_credentials():
        return flask.redirect(flask.url_for('index'))
    return flask.render_template("disable-credentials.html")

@app.route("/revoke-credentials")
def revoke_credentials():
    """Revoke credentials."""
    if not backup.check_credentials():
        return flask.redirect(flask.url_for('index'))
    credentials = backup.get_credentials()
    requests.post('https://oauth2.googleapis.com/revoke',
        params={'token': credentials.token},
        headers = {'content-type': 'application/x-www-form-urlencoded'})
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
    flow.fetch_token(authorization_response=authorization_response)
    backup.set_credentials(flow.credentials)

    return flask.redirect(flask.url_for('index'))


@app.route('/revoke')
def revoke():
    if 'credentials' not in flask.session:
        return ('You need to <a href="/authorize">authorize</a> before ' +
                'testing the code to revoke credentials.')

    credentials = backup.get_credentials()

    revoke = requests.post('https://oauth2.googleapis.com/revoke',
        params={'token': credentials.token},
        headers = {'content-type': 'application/x-www-form-urlencoded'})

    status_code = getattr(revoke, 'status_code')
    if status_code == 200:
        return('Credentials successfully revoked.')
    else:
        return('An error occurred.')


if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(host='localhost', port=8080, debug=True)
