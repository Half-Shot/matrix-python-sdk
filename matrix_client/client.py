# -*- coding: utf-8 -*-
# Copyright 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from .api import MatrixHttpApi, MatrixRequestError, MatrixUnexpectedResponse
from threading import Thread
import sys
# TODO: Finish implementing this.


class MatrixClient(object):
    """
    The client API for Matrix. For the raw HTTP calls, see MatrixHttpApi.

    Usage (new user):
        client = MatrixClient("https://matrix.org")
        token = client.register_with_password(username="foobar",
            password="monkey")
        room = client.create_room("myroom")
        room.send_image(file_like_object)

    Usage (logged in):
        client = MatrixClient("https://matrix.org", token="foobar")
        rooms = client.get_rooms()  # NB: From initial sync
        client.add_listener(func)  # NB: event stream callback
        rooms[0].add_listener(func)  # NB: callbacks just for this room.
        room = client.join_room("#matrix:matrix.org")
        response = room.send_text("Hello!")
        response = room.kick("@bob:matrix.org")

    Incoming event callbacks (scopes):

        def user_callback(user, incoming_event):
            pass

        def room_callback(room, incoming_event):
            pass

        def global_callback(incoming_event):
            pass

    """

    def __init__(self, base_url, token=None, valid_cert_check=True):
        """ Create a new Matrix Client object.

        Args:
            base_url (string): The url of the HS preceding /_matrix.
                e.g. (ex: https://localhost:8008 )
            token (Optional[string]): If you have an access token
                supply it here.
            valid_cert_check (Optional[bool]): Check the homeservers
                certificate on connections?

        Returns:
            MatrixClient

        Raises:
            MatrixRequestError
        """
        self.api = MatrixHttpApi(base_url, token)
        self.api.validate_certificate(valid_cert_check)
        self.listeners = []
        self.rooms = {
            # room_id: Room
        }
        if token:
            self._sync()

    def register_with_password(self, username, password, limit=1):
        """ Register for a new account on this HS.

        Args:
            username (string): Account username
            password (string): Account password
            limit (int): How many messages to return when syncing.

        Returns:
            string: Access Token

        Raises:
            MatrixRequestError
        """
        response = self.api.register(
            "m.login.password", user=username, password=password
        )
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        self._sync(limit)
        return self.token

    def login_with_password(self, username, password, limit=1):
        """ Login to the homeserver.

        Args:
            username (string): Account username
            password (string): Account password
            limit (int): How many messages to return when syncing.

        Returns:
            string: Access token

        Raises:
            MatrixRequestError
        """
        response = self.api.login(
            "m.login.password", user=username, password=password
        )
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        self._sync(limit)
        return self.token

    def create_room(self, alias=None, is_public=False, invitees=()):
        """ Create a new room on the homeserver.

        Args:
            alias (string): The canonical_alias of the room.
            is_public (bool):  The public/private visibility of the room.
            invitees (string[]): A set of user ids to invite into the room.

        Returns:
            Room

        Raises:
            MatrixRequestError
        """
        response = self.api.create_room(alias, is_public, invitees)
        return self._mkroom(response["room_id"])

    def join_room(self, room_id_or_alias):
        """ Join a room.

        Args:
            room_id_or_alias (string): Room ID or an alias.

        Raises:
            MatrixRequestError
        """
        response = self.api.join_room(room_id_or_alias)
        room_id = (
            response["room_id"] if "room_id" in response else room_id_or_alias
        )
        return self._mkroom(room_id)

    def get_rooms(self):
        """ Return a list of Room objects that the user has joined.

        Returns:
            Room[]: Rooms the user has joined.

        """
        return self.rooms

    def add_listener(self, callback):
        """ Add a listener that will send a callback when the client recieves
            an event.
        Args:
            callback (func(roomchunk)): Callback called when an event arrives.
        """
        self.listeners.append(callback)

    def listen_for_events(self, timeout=30000):
        """ Listen once for events. Use listen_forever to block indefinitely.

        Args:
            timeout (int): How long to poll the Home Server for before
                           retrying.
        """
        response = self.api.event_stream(self.end, timeout)
        self.end = response["end"]

        for chunk in response["chunk"]:
            for listener in self.listeners:
                listener(chunk)
            if "room_id" in chunk:
                if chunk["room_id"] not in self.rooms:
                    self._mkroom(chunk["room_id"])
                self.rooms[chunk["room_id"]].events.append(chunk)
                for listener in self.rooms[chunk["room_id"]].listeners:
                    listener(chunk)

    def listen_forever(self, timeout=30000):
        """ Keep listening for events forever.

        Args:
            timeout (int): How long to poll the Home Server for before
                           retrying.
        """
        while(True):
            self.listen_for_events(timeout)

    def start_listener_thread(self, timeout=30000):
        """ Start a listener thread to listen for events in the background.

        Args:
            timeout (int): How long to poll the Home Server for before
                           retrying.
        """
        try:
            thread = Thread(target=self.listen_forever, args=(timeout, ))
            thread.daemon = True
            thread.start()
        except:
            e = sys.exc_info()[0]
            print("Error: unable to start thread. " + str(e))

    def upload(self, content, content_type):
        """ Upload content to the home server and recieve a MXC url.

        Args:
            content (bytes): The data of the content.
            content_type (string): The mimetype of the content.

        Raises:
            MatrixUnexpectedResponse: If the homeserver gave a strange response
            MatrixRequestError: If the upload failed for some reason.
        """
        try:
            response = self.api.media_upload(content, content_type)
            if "content_uri" in response:
                return response["content_uri"]
            else:
                raise MatrixUnexpectedResponse(
                    "The upload was successful, but content_uri wasn't found."
                )
        except MatrixRequestError as e:
            raise MatrixRequestError(
                code=e.code,
                content="Upload failed: %s" % e
            )

    def _mkroom(self, room_id):
        self.rooms[room_id] = Room(self, room_id)
        return self.rooms[room_id]

    def _process_state_event(self, state_event, current_room):
        if "type" not in state_event:
            return  # Ignore event

        etype = state_event["type"]

        if etype == "m.room.name":
            current_room.name = state_event["content"]["name"]
        elif etype == "m.room.topic":
            current_room.topic = state_event["content"]["topic"]
        elif etype == "m.room.aliases":
            current_room.aliases = state_event["content"]["aliases"]

    def _sync(self, limit=1):
        response = self.api.initial_sync(limit)
        try:
            self.end = response["end"]
            for room in response["rooms"]:
                self._mkroom(room["room_id"])

                current_room = self.get_rooms()[room["room_id"]]
                for chunk in room["messages"]["chunk"]:
                    current_room.events.append(chunk)

                for state_event in room["state"]:
                    self._process_state_event(state_event, current_room)

        except KeyError:
            pass

    def get_user(self, user_id):
        """ Return a User by their id.
            NOTE: This function only returns a user object, it does not verify
            the user with the Home Server.

        Args:
            user_id (string): The matrix user id of a user.
        """
        return User(self.api, user_id)


class Room(object):
    """ The Room class can be used to call room specific functions
        after joining a room from the Client.
    """
    def __init__(self, client, room_id):
        """ Create a blank Room object.
            NOTE: This should ideally be called from within the Client.
            NOTE: This does not verify the room with the Home Server.
        """
        self.room_id = room_id
        self.client = client
        self.listeners = []
        self.events = []
        self.name = None
        self.aliases = []
        self.topic = None

    def send_text(self, text):
        """ Send a plain text message to the room.

        Args:
            text (string): The message to send
        """
        return self.client.api.send_message(self.room_id, text)

    def send_emote(self, text):
        """ Send a emote (/me style) message to the room.

        Args:
            text (string): The message to send
        """
        return self.client.api.send_emote(self.room_id, text)

    def send_notice(self, text):
        return self.client.api.send_notice(self.room_id, text)

    # See http://matrix.org/docs/spec/r0.0.1/client_server.html#m-image for the
    # imageinfo args.

    def send_image(self, url, name, **imageinfo):
        """ Send a pre-uploaded image to the room.
        See http://matrix.org/docs/spec/r0.0.1/client_server.html#m-image
        for imageinfo

        Args:
            url (string): The mxc url of the image.
            name (string): The filename of the image.
            imageinfo (): Extra information aboutt
        """
        return self.client.api.send_content(
            self.room_id, url, name, "m.image",
            extra_information=imageinfo
        )

    def add_listener(self, callback):
        """ Add a callback handler for events going to this room.

        Args:
            callback (func(roomchunk)): Callback called when an event arrives.
        """
        self.listeners.append(callback)

    def get_events(self):
        """ Get the most recent events for this room.

        Returns:
            events
        """
        return self.events

    def invite_user(self, user_id):
        """ Invite a user to this room

        Args:
            user_id (string): The matrix user id of a user.

        Returns:
                boolean: The invitation was sent.
        """
        try:
            self.client.api.invite_user(self.room_id, user_id)
            return True
        except MatrixRequestError:
            return False

    def kick_user(self, user_id, reason=""):
        """ Kick a user from this room

        Args:
            user_id (string): The matrix user id of a user.

        Returns:
                boolean: The user was kicked.
        """
        try:
            self.client.api.kick_user(self.room_id, user_id)
            return True
        except MatrixRequestError:
            return False

    def ban_user(self, user_id, reason):
        """ Ban a user from this room

        Args:
            user_id (string): The matrix user id of a user.
            reason  (string): A reason for banning the user.

        Returns:
                boolean: The user was banned.
        """
        try:
            self.client.api.ban_user(self.room_id, user_id, reason)
            return True
        except MatrixRequestError:
            return False

    def leave(self):
        """ Leave the room.

        Returns:
                boolean: Leaving the room was successful.
        """
        try:
            self.client.api.leave_room(self.room_id)
            self.client.rooms.remove(self.room_id)
            return True
        except MatrixRequestError:
            return False

    def update_room_name(self):
        """ Get room name

        Returns:
                boolean: True if the room name changed, False if not
        """
        try:
            response = self.client.api.get_room_name(self.room_id)
            if "name" in response and response["name"] != self.name:
                self.name = response["name"]
                return True
            else:
                return False
        except MatrixRequestError:
            return False

    def update_room_topic(self):
        """ Get room topic

        Returns:
                boolean: True if the topic changed, False if not
        """
        try:
            response = self.client.api.get_room_topic(self.room_id)
            if "topic" in response and response["topic"] != self.topic:
                self.topic = response["topic"]
                return True
            else:
                return False
        except MatrixRequestError:
            return False

    def update_aliases(self):
        """ Get aliases information from room state

        Returns:
                boolean: True if the aliases changed, False if not
        """
        try:
            response = self.client.api.get_room_state(self.room_id)
            for chunk in response:
                if "content" in chunk and "aliases" in chunk["content"]:
                    if chunk["content"]["aliases"] != self.aliases:
                        self.aliases = chunk["content"]["aliases"]
                        return True
                    else:
                        return False
        except MatrixRequestError:
            return False


class User(object):
    """
    The User class can be used to call user specific functions.
    """

    def __init__(self, api, user_id):
        self.user_id = user_id
        self.api = api

    def get_display_name(self):
        """ Get this users display name.

        Returns:
                string: Display Name
        """
        return self.api.get_display_name(self.user_id)

    def set_display_name(self, display_name):
        """ Set this users display name.

        Args:
                display_name (string): Display Name
        """
        return self.api.set_display_name(self.user_id, display_name)

    def get_avatar_url(self):
        mxcurl = self.api.get_avatar_url(self.user_id)
        url = self.api.get_download_url(mxcurl)
        return url

    def set_avatar_url(self, avatar_url):
        """ Set this users avatar.

        Args:
                avatar_url (string): mxc url from previously uploaded
        """
        return self.api.set_avatar_url(self.user_id, avatar_url)
