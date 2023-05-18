import flask
import functools
import math
import os
import requests
import threading
import google_auth_oauthlib.flow
import google.oauth2.credentials
import googleapiclient.discovery
import oauthlib.oauth2.rfc6749.errors
import settings

from typing import Any
from gphotosbackup import models, utils
from gphotosbackup import GPhotosBackup

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid',
          'https://www.googleapis.com/auth/photoslibrary.readonly',
          'https://www.googleapis.com/auth/userinfo.email']

app = flask.Flask(__name__)
app.secret_key = 'NOT REALLY NEEDED FOR LOCAL USAGE!'
os.makedirs(os.path.abspath(settings.STORAGE_PATH), exist_ok=True)
db = models.DB(f'sqlite:///{settings.STORAGE_PATH}/db.sqlite3')
global_crawler_lock = threading.Event()

def authorized_user(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        authorized_user = None
        if 'user_id' in flask.session:
            authorized_user = db.get_user_by(id=flask.session['user_id'])
        result = func(*args, **kwargs, authorized_user=authorized_user)
        return result
    return wrapper


@app.route("/")
@authorized_user
def index(authorized_user: Any):
    warning = None
    if 'warning' in flask.session:
        warning = flask.session['warning']
        del flask.session['warning']
    if 'user_id' not in flask.session:
        return flask.render_template('login.html', warning=warning)
    if 'credentials' not in flask.session:
        return flask.render_template('login.html', warning=warning)
    if not authorized_user:
        del flask.session['user_id']
        del flask.session['credentials']
        return flask.render_template('login.html', warning='User not found.')
    
    return flask.render_template('index.html', 
                                 authorized_user=authorized_user,
                                 warning=warning)


@app.route("/run")
def run():
    if 'user_id' not in flask.session or 'credentials' not in flask.session:
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
                                   db=db,
                                   storage_path=settings.STORAGE_PATH)

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


@app.route('/users')
@authorized_user
def users(authorized_user: Any):
    """Explore photos."""
    users = db.get_users()
    return flask.render_template('users.html',
                                 authorized_user=authorized_user,
                                 users=users)

@app.route('/users/<int:user_id>/mediaitems')
@app.route('/users/<int:user_id>/mediaitems/<int:page>')
@authorized_user
def user_mediaitems(authorized_user: Any, user_id: int, page: int = 1):
    """Explore media items."""
    user = db.get_user_by(id=user_id)
    if not user:
        return flask.abort(404, 'User not found.')
    total_mediaitems = db.get_user_mediaitems_total(user_id=user.id)
    total_pages = max(1, math.ceil(total_mediaitems/utils.ITEMS_PER_PAGE))
    if page > total_pages or page < 1:
        return flask.abort(404, 'Page not found.')
    mediaitems = db.get_user_mediaitems(user_id=user.id,
                                        offset=(page - 1) * utils.ITEMS_PER_PAGE,
                                        number=utils.ITEMS_PER_PAGE)
    return flask.render_template('photos.html',
                                 authorized_user=authorized_user,
                                 mediaitems=mediaitems,
                                 user=user,
                                 page=page,
                                 total_pages=total_pages)


@app.route('/users/<int:user_id>/albums')
@app.route('/users/<int:user_id>/albums/<int:page>')
@authorized_user
def user_albums(authorized_user: Any, user_id: int, page: int = 1):
    """Explore albums."""
    user = db.get_user_by(id=user_id)
    if not user:
        return flask.abort(404, 'User not found.')
    total_albums = db.get_user_albums_total(user_id=user.id)
    total_pages = max(1, math.ceil(total_albums/utils.ITEMS_PER_PAGE))
    if page > total_pages or page < 1:
        return flask.abort(404, 'Page not found.')
    albums = db.get_user_albums(user_id=user.id,
                                offset=(page - 1) * utils.ITEMS_PER_PAGE,
                                number=utils.ITEMS_PER_PAGE)
    return flask.render_template('albums.html',
                                 authorized_user=authorized_user,
                                 albums=albums,
                                 user=user,
                                 page=page,
                                 total_pages=total_pages)


@app.route('/users/<int:user_id>/albums/<int:album_id>/mediaitems')
@app.route('/users/<int:user_id>/albums/<int:album_id>/mediaitems/<int:page>')
@authorized_user
def user_albumitems(authorized_user: Any, user_id: int, album_id: int,
                    page: int = 1):
    """Explore album items."""
    user = db.get_user_by(id=user_id)
    if not user:
        return flask.abort(404, 'User not found.')
    album = db.get_user_album_by(user_id=user.id, id=album_id)
    if not album:
        return flask.abort(404, 'Album not found.')

    total_albumitems = db.get_albumitems_total(album_uid=album.album_uid)
    total_pages = max(1, math.ceil(total_albumitems/utils.ITEMS_PER_PAGE))
    if page > total_pages or page < 1:
        return flask.abort(404, 'Page not found.')
    mediaitems = db.get_albumitems(album_uid=album.album_uid,
                                   offset=(page - 1) * utils.ITEMS_PER_PAGE,
                                   number=utils.ITEMS_PER_PAGE)
    return flask.render_template('photos.html',
                                 authorized_user=authorized_user,
                                 mediaitems=mediaitems,
                                 user=user,
                                 page=page,
                                 total_pages=total_pages,
                                 album=album)


@app.route('/library/<int:user_id>/thumbnails/<int:mediaitem_id>')
def library_thumbnail(user_id: int, mediaitem_id: int):
    user = db.get_user_by(id=user_id)
    if not user:
        return flask.abort(404, 'User not found.')
    mediaitem = db.get_user_mediaitem_by(user_id=user_id, id=mediaitem_id)
    if not mediaitem:
        return flask.abort(404, 'Media item not found.')
    if not mediaitem.thumbnail:
        return flask.abort(404, 'Thumbnail not found.')
    abs_path_thumbnail = os.path.abspath(os.path.join(settings.STORAGE_PATH,
                                                      user.email,
                                                      utils.THUMBNAILS_FOLDER,
                                                      mediaitem.thumbnail))
    if not os.path.exists(abs_path_thumbnail):
        return flask.abort(404, 'Thumbnail not found.')
    return flask.send_from_directory(os.path.dirname(abs_path_thumbnail),
                                     os.path.basename(abs_path_thumbnail))


@app.route('/library/<int:user_id>/mediaitems/<int:mediaitem_id>')
def library_mediaitem(user_id, mediaitem_id):
    user = db.get_user_by(id=user_id)
    if not user:
        return flask.abort(404, 'User not found.')
    mediaitem = db.get_user_mediaitem_by(user_id=user_id, id=mediaitem_id)
    if not mediaitem:
        return flask.abort(404, 'Media item not found.')
    if not mediaitem.filename:
        return flask.abort(404, 'Media item not found.')
    abs_path_filename = os.path.abspath(os.path.join(settings.STORAGE_PATH,
                                                     user.email,
                                                     mediaitem.filename))
    if not os.path.exists(abs_path_filename):
        return flask.abort(404, 'Media item not found.')
    return flask.send_from_directory(os.path.dirname(abs_path_filename),
                                     os.path.basename(abs_path_filename))


@app.errorhandler(404)
def not_found(e):
    """Not Found page."""
    return flask.render_template('404.html'), 404


if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(host='localhost', port=8080, debug=True)
