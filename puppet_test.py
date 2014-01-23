#!/usr/bin/env python
import docker
import sys
import os
import shlex
import subprocess
import logging
import time
import argparse
import tempfile
from multiprocessing import Pool
from threading import Timer
import datetime
import shutil
import yaml
import fnmatch, re
import time
import math
from jinja2 import Environment, FileSystemLoader, meta

logging.basicConfig(format='%(asctime)-15s %(levelname)s:%(message)s', level=logging.INFO)

# Retry decorator with exponential backoff
def retry(tries, delay=3, backoff=2):
    '''Retries a function or method until it returns True.

    delay sets the initial delay in seconds, and backoff sets the factor by which
    the delay should lengthen after each failure. backoff must be greater than 1,
    or else it isn't really a backoff. tries must be at least 0, and delay
    greater than 0.'''

    if backoff <= 1:
      raise ValueError("backoff must be greater than 1")

    tries = math.floor(tries)
    if tries < 0:
      raise ValueError("tries must be 0 or greater")

    if delay <= 0:
      raise ValueError("delay must be greater than 0")

    def deco_retry(f):
      def f_retry(*args, **kwargs):
        mtries, mdelay = tries, delay # make mutable

        rv = f(*args, **kwargs) # first attempt
        while mtries > 0:
          if rv is True: # Done on success
            return True

          mtries -= 1      # consume an attempt
          time.sleep(mdelay) # wait...
          mdelay *= backoff  # make future wait longer

          rv = f(*args, **kwargs) # Try again

        return False # Ran out of tries :-(

      return f_retry # true decorator -> decorated function
    return deco_retry  # @retry(arg[, ...]) -> true decorator

class PuppetContainer:
    def __init__(self, rsa_key,
                 container_name = None,
                 puppet_facter_module = 'base',
                 puppet_facter_role = 'base',
                 puppet_facter_platform = 'lxc',
                 docker_image = 'spil/slc-puppet-base',
                 docker_image_tag = '6.5',
                 interactive = False,
                 ssh_user = 'root',
                 puppet_src_dir = '/vagrant',
                 docker_base_url = 'unix://var/run/docker.sock',
                 lifetime_limit = 600):
        if not container_name:
                self.container_name = "puppet_%s" % puppet_facter_module
        else:
                self.container_name = container_name
        self.rsa_key = rsa_key
        self.ssh_user = ssh_user
        self.docker_image = docker_image
        self.puppet_facter_module = puppet_facter_module
        self.puppet_facter_role = puppet_facter_role
        self.puppet_facter_platform = puppet_facter_platform
        self.docker_image = docker_image
        self.docker_image_tag = docker_image_tag
        self.interactive = interactive
        self.docker_base_url = docker_base_url
        self.puppet_src_dir = puppet_src_dir
        self._docker_connection = None
        self.lifetime_limit = lifetime_limit

    @property
    def docker_client(self):
        try:
            #try to get something from docker, reconnect in case of failure
            self._docker_connection.info()
        except:
            self._docker_connection = docker.Client(base_url=self.docker_base_url)
        return self._docker_connection

    def remove(self):
        """ Remove container.
            If container is in running state - stops it before removal.
        """
        try:
            inspect = self.docker_client.inspect_container(self.container_name)
        except docker.APIError as e:
            # raise APIError(e, response, explanation=explanation)
            # APIError: 404 Client Error: Not Found ("No such container: puppeta")
            logging.info(e.explanation)
            return 0

        if inspect['State']['Running']:
            logging.info('Container "%s" detected in a "running" state... stop and remove' % self.container_name)
            self.docker_client.stop(self.container_name)
        else:
            logging.info('Container "%s" detected... remove' % self.container_name)

        logging.info('Removing container "%s"' % self.container_name)
        self.docker_client.remove_container(self.container_name)
        return 0

    def emergency_exit(self):
        logging.info("Emergency exit: %s !!!!" % self.container_name)
        #self.remove()
        self.docker_client.stop(self.container_name)

    @retry(tries=4,delay=1, backoff=2)
    def test_ssh(self, ip):
        task = prepare_ssh_test_command(ip, self.rsa_key, self.ssh_user)

        (retcode, stdout, stderr) = run_and_capture_output(task,ignore_error=True)
        if retcode == 0:
            return True
        else:
            return False

    def kick(self):
        logging.info('Create container: %s' % self.container_name)
        if not self.docker_client.images(self.docker_image):
            stderr = "Docker error: Can not find image %s" % self.docker_image
            logging.error(stderr)
            result = {'puppet_module':self.puppet_facter_module, 'task':None, 'retcode':1, 'stdout':None, 'stderr':stderr, 'time':None}
            return result

        self.docker_client.create_container("%s:%s" % (self.docker_image, self.docker_image_tag),
                                            command=["/root/puppet/docker/init.sh"],
                                            stdin_open=True, tty=True,volumes=['/root/puppet'],
                                            name=self.container_name)

        time.sleep(1)

        logging.info('Start')
        self.docker_client.start(self.container_name,binds={self.puppet_src_dir: '/root/puppet'})

        time.sleep(2)

        try:
            inspect = self.docker_client.inspect_container(self.container_name)
        except APIError as e:
            # raise APIError(e, response, explanation=explanation)
            # APIError: 404 Client Error: Not Found ("No such container: puppeta")
            stdout = "Docker error: Can not inspect container %s" %  self.container_name
            logging.error(stdout)
            stderr = e.explanation
            logging.error(stderr)
            result = {'puppet_module':self.puppet_facter_module,
                      'task':None, 'retcode':1,
                      'stdout':stdout, 'stderr':stderr, 'time':None}
            return result

        if not inspect['State']['Running']:
            stdout = "Docker error: Can not detect running container %s" %  self.container_name
            stderr = self.docker_client.logs(self.container_name)
            logging.error(stdout)
            logging.error('Output:')
            logging.error(stderr)
            result = {'puppet_module':self.puppet_facter_module,
                      'task':None, 'retcode':1,
                      'stdout':stdout, 'stderr':stderr, 'time':None}
            return result

        logging.info('Container is running')

        if not inspect['NetworkSettings']['IPAddress']:
            stdout = 'Docker error: IPAddress does not set!'
            stderr = self.docker_client.logs(self.container_name)
            logging.error(stdout)
            logging.error('Output:')
            logging.error(stderr)
            result = {'puppet_module':self.puppet_facter_module,
                      'task':None, 'retcode':1,
                      'stdout':stdout, 'stderr':stderr, 'time':None}
            return result

        logging.info("Address: %s" % inspect['NetworkSettings']['IPAddress'])
        time.sleep(3)

	ip = inspect['NetworkSettings']['IPAddress']

        if not self.test_ssh(ip):
            logging.error('Can not establish ssh connection: %s' % ip)
            result = {'puppet_module':self.puppet_facter_module,
                      'task':None, 'retcode':1,
                      'stdout':stdout, 'stderr':stderr, 'time':None}
            return result


	task = prepare_puppet_command(inspect['NetworkSettings']['IPAddress'],
				      self.puppet_facter_role,
				      self.puppet_facter_module,
				      self.rsa_key,
				      self.ssh_user)
        stdout = ''
        stderr = ''
        time_start = 0
        time_finish = 0

        time_start = datetime.datetime.now().replace(microsecond=0)
        t = Timer(self.lifetime_limit, self.emergency_exit)
        t.start()
        if self.interactive:
            retcode = run_and_show(task,ignore_error=True)
        if not self.interactive:
            (retcode, stdout, stderr) = run_and_capture_output(task,ignore_error=True)
        t.cancel()
        time_finish = datetime.datetime.now().replace(microsecond=0)

        time_delta = time_finish - time_start


        result = {'puppet_module':self.puppet_facter_module,
                  'puppet_failed': is_puppet_failed(retcode),
                  'task':task, 'retcode':retcode,
                  'stdout':stdout, 'stderr':stderr, 'time':str(time_delta)}

        return result


def run_and_show(cmd, ignore_error=False):
    cmd_list = shlex.split(str(cmd))
    process = subprocess.Popen(cmd_list)
    (stdout, stderr) = process.communicate()
    retcode = process.returncode
    if retcode and not ignore_error:
        raise SubprocessException("'%s' failed(%d)" % (cmd, retcode), retcode)
    if retcode and ignore_error:
        logging.debug('Non zero exit code, but ignore: %s' % retcode)
    return retcode


def run_and_capture_output(cmd, ignore_error=False):
    """
    Function to call a subprocess and gather the output.
    """
    cmd_list = shlex.split(str(cmd))

    # NOTE: it is very, very important that we use temporary files for
    # collecting stdout and stderr here.  There is a nasty bug in python
    # subprocess; if your process produces more than 64k of data on an fd that
    # is using subprocess.PIPE, the whole thing will hang. To avoid this, we
    # use temporary fds to capture the data
    stdouttmp = tempfile.TemporaryFile()
    stderrtmp = tempfile.TemporaryFile()

    process = subprocess.Popen(cmd_list, stdout=stdouttmp, stderr=stderrtmp)
    process.communicate()
    retcode = process.poll()

    stdouttmp.seek(0, 0)
    stdout = stdouttmp.read()
    stdouttmp.close()

    stderrtmp.seek(0, 0)
    stderr = stderrtmp.read()
    stderrtmp.close()

    if retcode and not ignore_error:
        raise SubprocessException("'%s' failed(%d): %s" % (cmd_list, retcode, stderr), retcode)
    if retcode and ignore_error:
        logging.debug('Non zero exit code, but ignore: %s' % retcode)
    return (retcode, stdout, stderr)

def prepare_puppet_command(ipaddress, puppet_facter_role, puppet_facter_module, rsa_key, ssh_user):
    puppet_run_command = "ln -sf /root/puppet/hieradata /etc/puppet/ && cd /root/puppet && FACTER_module='%(puppet_facter_module)s' FACTER_platform='lxc' FACTER_spil_environment='puppet_test' FACTER_role=%(puppet_facter_role)s puppet apply --hiera_config /root/puppet/modules/puppet/files/hiera.yaml --detailed-exitcodes --verbose --debug --modulepath '/root/puppet/modules' manifests/site.pp" % {'puppet_facter_role':puppet_facter_role,'puppet_facter_module':puppet_facter_module}

    ssh_command = "ssh -o LogLevel=FATAL -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o IdentitiesOnly=yes -i %(rsa_key)s %(ssh_user)s@%(ipaddress)s '%(puppet_run_command)s'" % {'ipaddress':ipaddress,'puppet_run_command':puppet_run_command,'rsa_key':rsa_key,'ssh_user':ssh_user}
    logging.info('SSH command: %s' % ssh_command)
    return ssh_command

def prepare_ssh_test_command(ipaddress, rsa_key, ssh_user):
    ssh_command = "ssh -o LogLevel=FATAL -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o IdentitiesOnly=yes -i %(rsa_key)s %(ssh_user)s@%(ipaddress)s '%(run)s'" % {'ipaddress':ipaddress,'run':'ls -la','rsa_key':rsa_key,'ssh_user':ssh_user}
    logging.debug('SSH command: %s' % ssh_command)
    return ssh_command

def test_container(pcontainer):
    pcontainer.remove()
    result = pcontainer.kick()
    pcontainer.remove()
    return result

def is_puppet_failed(retcode):
    #exit code of '2' means there were changes,
    #an exit code of '4' means there were failures during the transaction,
    #and an exit code of '6' means there were both changes and failures.
    if int(retcode) not in [0, 2]:
        return True
    else:
        return False

def find_files(directory, pattern):
    for root, dirs, files in os.walk(directory):
        for basename in files:
            if fnmatch.fnmatch(basename, pattern):
                filename = os.path.join(root, basename)
                yield filename

def find_puppet_modules(directory):
    puppet_modules = []
    find_files(directory, 'test.pp')
    for test_manifest_path in find_files(directory, 'test.pp'):
        m = re.search('modules/(.+?)/manifests', test_manifest_path)
        if m:
            puppet_modules.append(m.group(1))
    return puppet_modules

def jenkins_build_files_changed():
    """ Return list of files changed since the last jenkins build
        Require env variables to be set by jenkins build.
        To test outside jenkins build, set env variables manually:
         export GIT_PREVIOUS_COMMIT='bdd34...'
         export GIT_COMMIT='952c3...'
    """
    missing_keys = []
    for key in ['GIT_COMMIT','GIT_PREVIOUS_COMMIT']:
        if key not in os.environ:
            missing_keys.append(key)
    if missing_keys:
        logging.error('Jenkins environment variables are missing: %s' % missing_keys)
        raise Exception('Jenkins environment variables are missing', missing_keys)
    git_previous_commit = os.environ['GIT_PREVIOUS_COMMIT']
    git_commit = os.environ['GIT_COMMIT']
    cmd = "git diff --pretty=short %(git_commit_id)s  %(git_previous_commit_id)s --name-only" % {'git_commit_id':git_commit,'git_previous_commit_id':git_previous_commit}

    (retcode, stdout, stderr) = run_and_capture_output(cmd,ignore_error=True)
    if retcode:
        logging.error('Can not get git commits: %s' % cmd)
        raise Exception('Can not get git commits', cmd, stdout, stderr)
    return stdout.split()

def jenkins_build_puppet_modules_changed():
    files_changed = jenkins_build_files_changed()
    modules_changed = set()
    for file in files_changed:
        if file.startswith('modules'):
            try:
                module = file.split('/')[1]
                modules_changed.add(module)
            except IndexError:
                pass
    logging.info('Puppet modules changed: %s' % modules_changed)
    return modules_changed

def git_is_inside_work_tree():
    try:
        (retcode, stdout, stderr) = run_and_capture_output('git rev-parse --is-inside-work-tree',ignore_error=True)
    except OSError:
        logging.error("Error: unable to find \"git\" executable, check if \"git\" installed")
        raise

    if retcode != 0:
        return False
    return True

def results_pretty_print(results):
    for result in results:
        logging.info("====================================================================")
        logging.info("  Module: %s" % result['puppet_module'])
        logging.info("  Retcode: %s" % result['retcode'])
        logging.info("  Runtime: %s" % result['time'])

        if is_puppet_failed(result['retcode']):
            logging.info("  Result: FAILED")
            logging.info("  Task: %s" % result['task'])
            logging.info("  Stdout: ")
            logging.info(result['stdout'])
            logging.info("  Sterr: ")
            logging.info(result['stderr'])
        else:
            logging.info("  Result: SUCCESS")

        logging.info("====================================================================")

def results_save_report(results, reports_dir=os.getcwd(), do_render_html=False, template_dir=None):
    #result = {'puppet_module':self.puppet_facter_module, 'task':None, 'retcode':1, 'stdout':None, 'stderr':stderr, 'time':None}
    report_dir_path = os.path.abspath(os.path.join(reports_dir,'reports'))
    report_html_dir_path = os.path.abspath(os.path.join(report_dir_path,'html'))
    logging.info("Reports dir: '%s'" % report_dir_path)
    if os.path.exists(report_dir_path):
        shutil.rmtree(report_dir_path)
    if not os.path.exists(report_dir_path):
        os.makedirs(report_dir_path)
    for result in results:
        module_report_dir_path = os.path.join(report_dir_path, result['puppet_module'])
        stderr_log_file_path = os.path.abspath(os.path.join(module_report_dir_path,'stderr.txt'))
        stdout_log_file_path = os.path.abspath(os.path.join(module_report_dir_path,'stdout.txt'))
        result_yaml_file_path = os.path.abspath(os.path.join(module_report_dir_path,'result.yml'))
        if not os.path.exists(module_report_dir_path):
            os.makedirs(module_report_dir_path)
        with open(stderr_log_file_path,'w') as f:
            f.write(result['stderr'])
        with open(stdout_log_file_path,'w') as f:
            f.write(result['stdout'])

        with open(result_yaml_file_path,'w') as f:
            f.write(yaml.dump(result, default_flow_style=False))

    if do_render_html:
        from ansi2html import Ansi2HTMLConverter
        os.makedirs(report_html_dir_path)
        input_data = {}
        input_data['results'] = results
        result_html_file_path = os.path.abspath(os.path.join(report_html_dir_path,'index.html'))
        with open(result_html_file_path,'w') as f:
            f.write(template_render(template_dir, 'index.html', input_data))

        conv = Ansi2HTMLConverter()
        for result in results:
            stderr_html_file_path = os.path.abspath(os.path.join(report_html_dir_path,'%s_stderr.html' % result['puppet_module']))
            stdout_html_file_path = os.path.abspath(os.path.join(report_html_dir_path,'%s_stdout.html' % result['puppet_module']))
            with open(stderr_html_file_path,'w') as f:
                html = conv.convert(result['stderr'])
                f.write(html)
            with open(stdout_html_file_path,'w') as f:
                html = conv.convert(result['stdout'])
                f.write(html)


def clean_reports_dir(reports_dir=os.getcwd()):
    report_dir_path = os.path.abspath(os.path.join(reports_dir,'reports'))
    logging.debug("clean reports dir: '%s'" % report_dir_path)
    if os.path.exists(report_dir_path):
        shutil.rmtree(report_dir_path)

def template_render(template_dir, template_file, input_data):
    env = Environment( loader=FileSystemLoader(template_dir),lstrip_blocks=True, trim_blocks=True)
    template = env.get_template(template_file)

    template_source = env.loader.get_source(env, template_file)[0]
    parsed_content = env.parse(template_source)
    rendered = template.render(input_data)
    return rendered


if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='Test puppet using Docker and a pinch of magic',
        epilog="Example: ")

    parser.add_argument("--module","-m", dest="puppet_module",
            help="module to test")

    parser.add_argument("--jenkins","-j", dest="jenkins_job", action='store_true',
            help="test modules from jenkins build - autodetect puppet modules changed since last build")

    parser.add_argument('--autodetect-modules','-a', dest='autodetect_modules', action='store_true',
            help='search puppet directory to find modules with tests')

    parser.add_argument("--parallel","-p", dest="parallel_jobs", default=1, type=int,
            help="number of testing jobs to run in parallel")

    parser.add_argument('--skip-base-creation','--quick', dest='skip_base_image', action='store_true',
            help='do not create base image assuming its already exist, just run modules')

    parser.add_argument('--leave-base', dest='leave_base_image', action='store_true',
            help='do not delete base image after tests completed')

    parser.add_argument("--puppet-directory", dest="puppet_directory", default='/vagrant',
            help="path of the puppet directory")

    parser.add_argument("--docker_rsa_key","--rsa", dest="docker_rsa_key",
            help="path to the RSA key to access docker containers")

    parser.add_argument("--reports-dir",dest="reports_dir", default=os.getcwd(),
            help="directory to store reports")

    args = parser.parse_args()


    if os.path.exists(args.puppet_directory):
        os.chdir(args.puppet_directory)
    else:
        logging.error("Puppet directory does not exist: '%s', check '--puppet-directory'" % args.puppet_directory)
        sys.exit(1)

    clean_reports_dir(args.reports_dir)

    template_dir = os.path.join(args.puppet_directory, 'docker/templates')

    if not args.docker_rsa_key:
        docker_rsa_key_path = os.path.abspath(os.path.join(args.puppet_directory,'docker/docker_rsa'))
    else:
        docker_rsa_key_path = os.path.abspath(os.path.join(args.docker_rsa_key))

    if not os.path.exists(docker_rsa_key_path):
        logging.error("Can not find Docker RSA key: '%s'" % docker_rsa_key_path)
        sys.exit(1)

    logging.info("Docker RSA key: '%s'" % docker_rsa_key_path)

    if args.reports_dir and not os.path.exists(args.reports_dir):
            logging.error("Reports dir does not exist: '%s'" % args.reports_dir)
            sys.exit(1)
#####
#    results = [{'puppet_module': 'nginx', 'task': 'task', 'retcode': 'retcode', 'stdout': 'stdout', 'puppet_failed': 'True', 'stderr': 'stderr', 'time': '0:123'}, {'puppet_module': 'nginx1', 'task': 'task', 'retcode': 'retcode', 'stdout': 'stdout', 'puppet_failed': 'True', 'stderr': 'stderr', 'time': '0:123'}, {'puppet_module': 'nginx2', 'task': 'task', 'retcode': 'retcode', 'stdout': 'stdout', 'puppet_failed': 'True', 'stderr': 'stderr', 'time': '0:123'}]
#
#    results_save_report(results, args.reports_dir, True, templates_dir)
#    sys.exit(0)
######

    if args.puppet_module:
        puppet_facter_module = args.puppet_module
        puppet_modules = set(puppet_facter_module.split(','))
    else:
        puppet_modules = []

    if args.jenkins_job:
        if not git_is_inside_work_tree():
            logging.error("Working directory is outside a git tree: '%s', check '--puppet-directory'" % os.getcwd())
            sys.exit(1)
        puppet_modules = [module for module in jenkins_build_puppet_modules_changed() if module in find_puppet_modules(args.puppet_directory)]
        logging.info('Puppet modules to test: %s' % puppet_modules)

    if not args.puppet_module and not args.jenkins_job and args.autodetect_modules:
        puppet_modules = find_puppet_modules(args.puppet_directory)

    pcontainer = PuppetContainer(docker_image='spil/slc-puppet',
                                 docker_image_tag='6.5',
                                 puppet_src_dir=args.puppet_directory,
                                 rsa_key=docker_rsa_key_path)

    if not pcontainer.docker_client.images('spil/slc-puppet-base'):
        #base image is missing - build it anyway
        build_base_image = True
    elif args.skip_base_image:
        build_base_image = False
    else:
        build_base_image = True

    if args.leave_base_image or args.skip_base_image:
        remove_base_image = False
    else:
        remove_base_image = True

    results = []
    if build_base_image:
        # Create base image - will create container, apply puppet base role, and commit container to the docker base image
        if pcontainer.docker_client.images('spil/slc-puppet-base'):
            pcontainer.docker_client.remove_image('spil/slc-puppet-base:6.5')
        pcontainer.remove()
        result = pcontainer.kick()
        results.append(result)
        if int(result['retcode']) in [0, 2]:
            logging.info('Base puppet container created, commit to the docker image')
            pcontainer.docker_client.commit(pcontainer.container_name, repository='spil/slc-puppet-base', tag='6.5')
        else:
            results_pretty_print(results) # works only with a list of results
            logging.error('Base puppet container FAILED, check whats wrong with container "puppet_base" ... Bye')
            sys.exit(1)
        pcontainer.remove()

    pcontainer_list = []
    for module in puppet_modules:
        pcontainer = PuppetContainer(docker_image='spil/slc-puppet-base',
                                     docker_image_tag='6.5',
                                     puppet_facter_module=module,
                                     puppet_src_dir=args.puppet_directory,
                                     rsa_key=docker_rsa_key_path)
        pcontainer_list.append(pcontainer)

    p = Pool(int(args.parallel_jobs))
    results = results + p.map_async(test_container, pcontainer_list).get(timeout=600)
    results_pretty_print(results)
    results_save_report(results, args.reports_dir, do_render_html=True, template_dir=template_dir)

    if remove_base_image:
        print 'All test complete - remove base image'
        pcontainer.docker_client.remove_image('spil/slc-puppet-base:6.5')
