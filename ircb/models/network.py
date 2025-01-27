# -*- coding: utf-8 -*-

import datetime
from hashlib import md5

from sqlalchemy import (Column, String, Integer, ForeignKey, DateTime,
                        UniqueConstraint)
from sqlalchemy_utils import ChoiceType

from ircb.models.lib import Base, get_session
from ircb.models.user import User
from ircb.config import settings

NETWORK_STATUS_TYPES = (
    ('0', 'Connecting'),
    ('1', 'Connected'),
    ('2', 'Disconnecting'),
    ('3', 'Disconnected')
)
session = get_session()


def _create_access_token(user_id, network_name):
    user = session.query(User).get(user_id)
    return md5('{}{}{}{}'.format(settings.SECRET_KEY,
                                 user.username,
                                 network_name,
                                 datetime.datetime.utcnow()).encode()
               ).hexdigest()


class Network(Base):
    __tablename__ = 'networks'
    __table_args__ = (
        UniqueConstraint('user_id', 'name'),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    nickname = Column(String(20), nullable=False)
    hostname = Column(String(100), nullable=False)
    port = Column(Integer, nullable=False)
    realname = Column(String(100), nullable=False, default='')
    username = Column(String(50), nullable=False, default='')
    password = Column(String(100), nullable=False, default='')
    usermode = Column(String(1), nullable=False, default='0')
    access_token = Column(String(100), nullable=False, unique=True,
                          default=lambda context: _create_access_token(
                          context.current_parameters['user_id'],
                          context.current_parameters['name']))
    user_id = Column(
        Integer(), ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False)

    # Runtime fields
    current_nickname = Column(String(20), nullable=True)
    status = Column(ChoiceType(NETWORK_STATUS_TYPES))

    # timestamps
    created = Column(DateTime, default=datetime.datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow)

    def create_access_token(self):
        return _create_access_token(self.user.id, self.name)
