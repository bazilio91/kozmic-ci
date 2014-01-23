# coding: utf-8
import os
import time
import unittest
import tempfile
import Queue
import datetime as dt
import hashlib

import httpretty
import pytest
import redis
import mock
from flask import current_app
from flask.ext.principal import Need
from flask.ext.webtest import SessionScope

import kozmic.builds.tasks
import kozmic.builds.views
from kozmic import mail
from kozmic.models import db, Membership, User, Project, Build, TrackedFile
from . import TestCase, factories, func_fixtures, utils, unit_fixtures as fixtures


class TestUser(unittest.TestCase):
    @staticmethod
    @httpretty.httprettified
    def get_stub_for__get_gh_org_repos():
        """Returns a stub for :meth:`User.get_gh_org_repos`."""

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/user/teams',
            fixtures.TEAMS_JSON)

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/teams/267031/repos',
            fixtures.TEAM_267031_JSON)

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/teams/297965/repos',
            fixtures.TEAM_297965_JSON)

        rv = User(gh_access_token='123').get_gh_org_repos()
        return mock.Mock(return_value=rv)

    @staticmethod
    @httpretty.httprettified
    def get_stub_for__get_gh_repos():
        """Returns a stub for :meth:`User.get_gh_repos`."""

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/user/repos',
            fixtures.USER_REPOS_JSON)

        rv = User(gh_access_token='123').get_gh_repos()
        return mock.Mock(return_value=rv)

    def test_get_gh_org_repos(self):
        stub = self.get_stub_for__get_gh_org_repos()
        gh_orgs, gh_repos_by_org_id = stub.return_value

        assert len(gh_orgs) == 2
        pyconru_org, unistorage_org = \
            sorted(gh_orgs, key=lambda gh_org: gh_org.login)
        assert len(gh_repos_by_org_id[pyconru_org.id]) == 1
        assert len(gh_repos_by_org_id[unistorage_org.id]) == 6

    def test_get_gh_repos(self):
        stub = self.get_stub_for__get_gh_repos()
        assert len(stub.return_value) == 3


class TestUserDB(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user_1, self.user_2, self.user_3, self.user_4 = \
            factories.UserFactory.create_batch(4)

        factories.ProjectFactory.create_batch(3, owner=self.user_1)
        factories.ProjectFactory.create_batch(2, owner=self.user_2)
        factories.ProjectFactory.create_batch(1, owner=self.user_3)

        self.project_1, self.project_2, self.project_3, = self.user_1.owned_projects
        self.project_4, self.project_5 = self.user_2.owned_projects

        self.projects = {self.project_1, self.project_2, self.project_3,
                         self.project_4, self.project_5}

    def test_get_available_projects(self):
        for project in [self.project_4, self.project_5]:
            factories.MembershipFactory.create(
                user=self.user_1,
                project=project)

        factories.BuildFactory.create_batch(5, project=self.project_1)
        factories.BuildFactory.create_batch(5, project=self.project_2)
        factories.BuildFactory.create_batch(3, project=self.project_4)

        rv = self.user_1.get_available_projects()
        assert set(rv) == self.projects

        rv = self.user_1.get_available_projects(annotate_with_latest_builds=True)
        assert set(rv) == {(self.project_1, self.project_1.get_latest_build()),
                           (self.project_2, self.project_2.get_latest_build()),
                           (self.project_3, None),
                           (self.project_4, self.project_4.get_latest_build()),
                           (self.project_5, None)}

        assert set(self.user_2.get_available_projects()) == \
            {self.project_4, self.project_5}
        assert not self.user_4.get_available_projects()

    def test_get_identity(self):
        factories.MembershipFactory.create(
            user=self.user_1,
            project=self.project_4,
            allows_management=True)
        factories.MembershipFactory.create(
            user=self.user_1,
            project=self.project_5)

        identity = self.user_1.get_identity()
        assert identity.provides == {
            Need(method='project_owner', value=self.project_1.id),
            Need(method='project_owner', value=self.project_2.id),
            Need(method='project_owner', value=self.project_3.id),
            Need(method='project_manager', value=self.project_4.id),
            Need(method='project_member', value=self.project_5.id),
        }

        identity = self.user_2.get_identity()
        assert identity.provides == {
            Need(method='project_owner', value=self.project_4.id),
            Need(method='project_owner', value=self.project_5.id),
        }

        identity = self.user_4.get_identity()
        assert not identity.provides


class TestBuildDB(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)

    def test_get_ref_and_sha(self):
        get_ref_and_sha = kozmic.builds.views.get_ref_and_sha
        assert (get_ref_and_sha(func_fixtures.PULL_REQUEST_HOOK_CALL_DATA) ==
                (u'test', u'47fe2c74f6d46304830ed46afd59a53401b20b78'))
        assert (get_ref_and_sha(func_fixtures.PUSH_HOOK_CALL_DATA) ==
                (u'master', u'47fe2c74f6d46304830ed46afd59a53401b20b78'))

    def test_set_status(self):
        description = 'Something went very wrong'

        # 1. There are no members with email addresses
        build_1 = factories.BuildFactory.create(project=self.project)

        with mail.record_messages() as outbox:
            with mock.patch.object(Project, 'gh') as gh_repo_mock:
                build_1.set_status('failure', description=description)

        assert not outbox
        gh_repo_mock.create_status.assert_called_once_with(
            build_1.gh_commit_sha,
            'failure',
            target_url=build_1.url,
            description=description)

        # 2. There are members with email addresses
        member_1 = factories.UserFactory.create(email='john@doe.com')
        member_2 = factories.UserFactory.create(email='jane@doe.com')
        for member in [member_1, member_2]:
            factories.MembershipFactory.create(user=member, project=self.project)

        build_2 = factories.BuildFactory.create(project=self.project)

        with mail.record_messages() as outbox:
            with mock.patch.object(Project, 'gh') as gh_repo_mock:
                build_2.set_status('failure', description=description)

        assert len(outbox) == 1
        message = outbox[0]
        assert self.project.gh_full_name in message.subject
        assert 'failure' in message.subject
        assert build_2.gh_commit_ref in message.subject
        assert build_2.url in message.html

        gh_repo_mock.create_status.assert_called_once_with(
            build_2.gh_commit_sha,
            'failure',
            target_url=build_2.url,
            description=description)

        # 3. Repeat the same `set_status` call and make sure that we
        # will not be notified the second time
        with mail.record_messages() as outbox:
            with mock.patch.object(Project, 'gh') as gh_repo_mock:
                build_2.set_status('failure', description=description)

        assert not outbox
        assert not gh_repo_mock.create_status.called

    def test_calculate_number(self):
        build_1 = Build(
            project=self.project,
            gh_commit_sha='a' * 40,
            gh_commit_author='aromanovich',
            gh_commit_message='ok',
            gh_commit_ref='master',
            status='enqueued')
        build_1.calculate_number()
        db.session.add(build_1)
        db.session.commit()

        build_2 = Build(
            project=self.project,
            gh_commit_sha='b' * 40,
            gh_commit_author='aromanovich',
            gh_commit_message='ok',
            gh_commit_ref='master',
            status='enqueued')
        build_2.calculate_number()
        db.session.add(build_2)
        db.session.commit()

        assert build_1.number == 1
        assert build_2.number == 2


class TestHookDB(TestCase):
    def test_delete_cascade(self):
        """Tests that hook calls are preserved on hook delete."""
        user = factories.UserFactory.create()
        project = factories.ProjectFactory.create(owner=user)
        builds = factories.BuildFactory.create_batch(3, project=project)
        hook = factories.HookFactory.create(project=project)
        hook_calls = []
        for build in builds:
            hook_calls.append(
                factories.HookCallFactory.create(hook=hook, build=build))

        for hook_call in hook_calls:
            assert hook_call.hook_id == hook.id

        db.session.delete(hook)
        db.session.commit()

        for hook_call in hook_calls:
            assert hook_call.hook_id is None


KOZMIC_BLUES = '''
Time keeps movin' on,
Friends they turn away.
I keep movin' on
But I never found out why
I keep pushing so hard the dream,
I keep tryin' to make it right
Through another lonely day, whoaa.
'''.strip()


class TestTailer(TestCase):
    # We can't mock _kill_container method in ahother thread,
    # so just make it no-op to ease testing.
    class _Tailer(kozmic.builds.tasks.Tailer):
        def _kill_container(self):
            pass

    def test_tailer(self):
        config = current_app.config
        redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                         port=config['KOZMIC_REDIS_PORT'],
                                         db=config['KOZMIC_REDIS_DATABASE'])
        redis_client.delete('test')
        channel = redis_client.pubsub()
        channel.subscribe('test')
        listener = channel.listen()

        with tempfile.NamedTemporaryFile(mode='a+b') as f:
            tailer = self._Tailer(
                log_path=f.name,
                redis_client=redis_client,
                channel='test',
                container=mock.MagicMock())
            tailer.start()
            time.sleep(.5)

            # Skip "subscribe" message that looks like this:
            # {'channel': 'test', 'data': 1L, 'pattern': None, 'type': 'subscribe'}
            listener.next()

            for line in KOZMIC_BLUES.split('\n'):
                f.write(line + '\n')
                f.flush()
                assert listener.next()['data'] == line + '\n'

        time.sleep(.5)
        assert KOZMIC_BLUES + '\n' == ''.join(redis_client.lrange('test', 0, -1))

    def test_ansi_sequences_formatting(self):
        colored_lines = [
            '[4mRunning "jshint:lib" (jshint) task[24m',
            '[36m->[0m running [36m1 suite',  # intentionally omit "[0m"
        ]
        redis_mock = mock.MagicMock()
        tailer = self._Tailer(
            log_path='some-file.txt',
            redis_client=redis_mock,
            channel='test',
            container=mock.MagicMock())
        tailer._publish(colored_lines)

        expected_calls = [
            mock.call('test', '<span class="ansi4">Running "jshint:lib" '
                              '(jshint) task</span>\n'),
            mock.call('test', '<span class="ansi36">-&gt;</span> running '
                              '<span class="ansi36">1 suite</span>\n')
        ]
        assert redis_mock.rpush.call_args_list == expected_calls
        assert redis_mock.publish.call_args_list == expected_calls

    def test_kill_timeout_is_working(self):
        with tempfile.NamedTemporaryFile(mode='a+b') as f:
            tailer = self._Tailer(
                log_path=f.name,
                redis_client=mock.MagicMock(),
                channel='test',
                container={'Id': '564fe66af3aa755d79797e1'},
                kill_timeout=2)

            with mock.patch.object(tailer, '_kill_container') as kill_container_mock:
                with mock.patch.object(tailer, '_publish') as publish_mock:
                    tailer.start()
                    time.sleep(1)
                    assert not kill_container_mock.called
                    time.sleep(2)
                    kill_container_mock.assert_called_once_with()

            message = 'Sorry, your script has stalled and been killed.\n'
            assert message in f.read()
            publish_mock.assert_called_once_with([message])


@pytest.mark.docker
class TestBuilder(TestCase):
    def test_builder(self):
        passphrase = 'passphrase'
        private_key = utils.generate_private_key(passphrase)

        with kozmic.builds.tasks.create_temp_dir() as build_dir:
            head_sha = utils.create_git_repo(os.path.join(build_dir, 'test-repo'))

            message_queue = Queue.Queue()
            builder = kozmic.builds.tasks.Builder(
                rsa_private_key=private_key,
                passphrase=passphrase,
                docker_image='kozmic/ubuntu-base:12.04',
                script='#!/bin/bash\nbash ./kozmic.sh',
                working_dir=build_dir,
                clone_url='/kozmic/test-repo',
                commit_sha=head_sha,
                message_queue=message_queue)
            builder.start()
            container = message_queue.get(True, 60)
            assert isinstance(container, dict) and 'Id' in container
            message_queue.task_done()
            builder.join()

            log_path = os.path.join(build_dir, 'script.log')
            with open(log_path, 'r') as log:
                stdout = log.read().strip()

        assert not builder.exc_info
        assert builder.return_code == 0
        assert stdout == 'Hello!'

    def test_builder_with_wrong_passphrase(self):
        """Tests that Builder does not hang being called
        with a wrong passphrase.
        """
        with kozmic.builds.tasks.create_temp_dir() as build_dir:
            head_sha = utils.create_git_repo(os.path.join(build_dir, 'test-repo'))

            message_queue = Queue.Queue()
            builder = kozmic.builds.tasks.Builder(
                rsa_private_key=utils.generate_private_key('passphrase'),
                passphrase='wrong-passphrase',
                docker_image='kozmic/ubuntu-base:12.04',
                script='#!/bin/bash\nbash ./kozmic.sh',
                working_dir=build_dir,
                clone_url='/kozmic/test-repo',
                commit_sha=head_sha,
                message_queue=mock.MagicMock())
            builder.run()
        assert builder.return_code == 1


class BuilderStub(kozmic.builds.tasks.Builder):
    def run(self):
        time.sleep(1)

        self._message_queue.put({'Id': 'qwerty'}, block=True, timeout=60)
        self._message_queue.join()

        log_path = os.path.join(self._working_dir, 'script.log')
        with open(log_path, 'a') as log:
            log.write('Everything went great!\nGood bye.')

        self.return_code = 0


class TestBuildTaskDB(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.hook = factories.HookFactory.create(project=self.project)
        self.build = factories.BuildFactory.create(project=self.project)
        self.hook_call = factories.HookCallFactory.create(
            hook=self.hook, build=self.build)

    def test_do_job(self):
        with SessionScope(self.db):
            set_status_patcher = mock.patch.object(Build, 'set_status')
            builder_patcher = mock.patch('kozmic.builds.tasks.Builder', new=BuilderStub)
            tailer_patcher = mock.patch('kozmic.builds.tasks.Tailer')
            docker_patcher = mock.patch.multiple(
                'docker.Client', pull=mock.DEFAULT, inspect_image=mock.DEFAULT)

            set_status_mock = set_status_patcher.start()
            builder_patcher.start()
            tailer_patcher.start()
            docker_patcher.start()
            try:
                kozmic.builds.tasks.do_job(hook_call_id=self.hook_call.id)
            finally:
                docker_patcher.stop()
                tailer_patcher.stop()
                builder_patcher.stop()
                set_status_patcher.stop()
        self.db.session.rollback()

        assert self.build.jobs.count() == 1
        job = self.build.jobs.first()
        assert job.return_code == 0
        assert job.stdout == 'Everything went great!\nGood bye.'
        build_id = self.build.id
        set_status_mock.assert_has_calls([
            mock.call(
                'pending',
                description='Kozmic build #{} is pending.'.format(build_id)),
            mock.call(
                'success',
                description='Kozmic build #{} has passed.'.format(build_id)),
        ])

    @pytest.mark.docker
    def test_restart_build(self):
        job = factories.JobFactory.create(
            build=self.build,
            hook_call=self.hook_call,
            started_at=dt.datetime.utcnow() - dt.timedelta(minutes=2),
            finished_at=dt.datetime.utcnow(),
            stdout='output')

        assert self.build.jobs.count() == 1
        job_id_before_restart = job.id

        with SessionScope(self.db):
            set_status_patcher = mock.patch.object(Build, 'set_status')
            _run_patcher = mock.patch('kozmic.builds.tasks._run')

            set_status_mock = set_status_patcher.start()
            _run_mock = _run_patcher.start()
            _run_mock.return_value.__enter__ = mock.MagicMock(
                side_effect=lambda *args, **kwargs: (0, 'output', {'Id': 'container-id'}))
            try:
                kozmic.builds.tasks.restart_job(job.id)
            finally:
                _run_mock.stop()
                set_status_patcher.stop()
        self.db.session.rollback()

        assert self.build.jobs.count() == 1
        assert _run_mock.called
        assert _run_mock.return_value.__enter__.called

        job = self.build.jobs.first()
        assert job_id_before_restart != job.id
        assert job.return_code == 0
        assert job.stdout == 'output'


class TestJobDB(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.hook = factories.HookFactory.create(
            project=self.project,
            install_script='#!/bin/bash\npip install -r reqs.txt')
        self.build = factories.BuildFactory.create(project=self.project)
        self.hook_call = factories.HookCallFactory.create(
            hook=self.hook, build=self.build)
        self.job = factories.JobFactory.create(
            build=self.build, hook_call=self.hook_call)

    @mock.patch.object(Project, 'gh')
    def test_get_cache_id_changes_when_tracked_file_changes(self, gh_mock):
        self.hook.tracked_files.delete()
        self.hook.tracked_files.extend([
            TrackedFile(path='./a/../b/../install.sh'),
            TrackedFile(path='requirements'),
            TrackedFile(path='./Gemfile'),
        ])
        db.session.flush()

        dir_entries = ['requirements/basic.txt', 'requirements/dev.txt']
        deleted_paths = []

        def contents(path, ref=None):
            # Mock github3.repo.Repository.contents method
            if path == 'requirements':
                # Pretend that "requirements" is a directory
                return dict(zip(dir_entries, map(contents, dir_entries)))
            else:
                # Other paths are regular files, maybe deleted
                if path in deleted_paths:
                    return None
                rv = mock.MagicMock()  # Mock github3.repos.contents.Contents
                rv.sha = hashlib.sha256(path).hexdigest()
                return rv
        gh_mock.contents.side_effect = contents

        seen_cache_ids = set()

        # Compute the cache
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)

        # Make sure that `get_cache_id` asked GitHub API for contents
        # of all the tracked files using their normalized paths.
        # Also make sure that calls are made in lexicographical order
        assert gh_mock.contents.call_args_list == [
            mock.call('Gemfile', ref=self.build.gh_commit_sha),
            mock.call('install.sh', ref=self.build.gh_commit_sha),
            mock.call('requirements', ref=self.build.gh_commit_sha),
        ]

        # Add a new file to the tracked directory and
        # make sure the cache id is changed
        dir_entries.append('requirements/new-file.txt')
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)

        # Delete one of the tracked files and make sure the cache id is changed
        deleted_paths.append('install.sh')
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)

        # Change nothing and make sure the cache id is not changed
        cache_id = self.job.get_cache_id()
        assert cache_id in seen_cache_ids

    @mock.patch.object(Project, 'gh')
    def test_get_cache_id_changes_when_image_or_script_changes(self, _):
        seen_cache_ids = set()

        self.hook.install_script = ('#!/bin/bash\n'
                                    'pip install -r reqs.txt')
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)

        self.hook.install_script = ('#!/bin/bash\n'
                                    'apt-get install python-mysql\n'
                                    'pip install reqs.txt')
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)

        self.hook.docker_image = 'kozmic/debian'
        cache_id = self.job.get_cache_id()
        assert cache_id not in seen_cache_ids
        seen_cache_ids.add(cache_id)
