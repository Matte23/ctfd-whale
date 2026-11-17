import uuid
from datetime import datetime

from CTFd.models import Challenges, db

from .utils.templates import render_http_subdomain


class DockerChallenges(Challenges):
    __mapper_args__ = {"polymorphic_identity": "docker"}
    id = db.Column(
        db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"),
        primary_key=True,
    )

    flag_template = db.Column(db.Text, default="")
    memory_limit = db.Column(db.Text, default="128m")
    cpu_limit = db.Column(db.Float, default=0.5)
    init = db.Column(db.Boolean, default=False)
    privileged = db.Column(db.Boolean, default=False)

    docker_image = db.Column(db.Text)
    redirect_type = db.Column(db.Text)
    redirect_port = db.Column(db.Integer)


class WhaleContainer(db.Model):
    # status values. REMOVING: removal failed partway, auto-clean retries it;
    # the container no longer counts as the user's running instance.
    STATUS_RUNNING = 1
    STATUS_REMOVING = 2

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # SET NULL, not CASCADE: deleting a user, challenge or flag must keep the
    # row, otherwise auto-clean can't find the docker resources to remove
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="SET NULL"), nullable=True
    )
    # UTC, like CTFd's own timestamps
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    renew_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.Integer, default=STATUS_RUNNING)
    uuid = db.Column(db.String(256))
    # docker name and whale_id label of the resources: "<user_id>-<uuid>".
    # Stored so the resources can still be found once user_id is NULL.
    name = db.Column(db.String(256))
    # Resources held by the container, allocated in utils/db.py. Unique, so
    # two containers can never get the same one; deleting the row (only done
    # once the docker resources are gone) frees them. NULL: none held.
    port = db.Column(db.Integer, nullable=True, unique=True)
    subnet = db.Column(db.String(64), nullable=True, unique=True)
    flag_id = db.Column(
        db.Integer, db.ForeignKey("flags.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    user = db.relationship(
        "Users", foreign_keys="WhaleContainer.user_id", lazy="select"
    )
    challenge = db.relationship(
        "DockerChallenges",
        foreign_keys="WhaleContainer.challenge_id",
        lazy="select",
    )
    flag = db.relationship(
        "Flags", foreign_keys="WhaleContainer.flag_id", lazy="select"
    )

    @property
    def is_removing(self):
        return self.status == WhaleContainer.STATUS_REMOVING

    @property
    def http_subdomain(self):
        return render_http_subdomain(self)

    def __init__(self, user_id, challenge_id, flag_id):
        self.user_id = user_id
        self.challenge_id = challenge_id
        self.start_time = datetime.utcnow()
        self.renew_count = 0
        self.uuid = str(uuid.uuid4())
        self.name = f"{user_id}-{self.uuid}"
        self.flag_id = flag_id

    @property
    def user_access(self):
        """How to reach the container: the same text players get (plain text)."""
        if self.challenge is None:
            return ""
        # imported here: the routers import this module
        from .utils.routers import get_router

        return get_router().access(self)

    def __repr__(self):
        return "<WhaleContainer ID:{0} {1} {2} {3} {4}>".format(
            self.id, self.user_id, self.challenge_id, self.start_time, self.renew_count
        )
