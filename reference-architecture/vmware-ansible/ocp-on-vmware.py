#!/usr/bin/env python
# set ts=4 sw=4 et
import argparse, click, datetime,  os, sys, fileinput, json, iptools, ldap, six, random, yaml
from argparse import RawTextHelpFormatter
import requests
from six.moves import configparser


class VMwareOnOCP(object):

    __name__ = 'VMwareOnOCP'
    console_port=8443
    cluster_id=None
    deployment_type=None
    openshift_vers=None
    vcenter_host=None
    vcenter_username=None
    vcenter_password=None
    vcenter_template_name=None
    vcenter_folder=None
    vcenter_cluster=None
    vcenter_datacenter=None
    vcenter_datastore=None
    vcenter_resource_pool=None
    dns_zone=None
    app_dns_prefix=None
    vm_dns=None
    vm_gw=None
    vm_netmask=None
    vm_network=None
    rhel_subscription_user=None
    rhel_subscription_pass=None
    rhel_subscription_server=None
    rhel_subscription_pool=None
    rhsm_katello_url=None
    rhsm_activation_key=None
    rhsm_org_id=None
    byo_lb=None
    lb_config=''
    lb_host=None
    lb_ha_ip=None
    byo_nfs=None
    nfs_host=None
    nfs_registry_mountpoint=None
    no_confirm=False
    tag=None
    verbose=0
    create_inventory=None
    master_nodes=None
    infra_nodes=None
    app_nodes=None
    support_nodes=None
    vm_ipaddr_start=None
    ocp_hostname_prefix=None
    create_ocp_vars=None
    auth_type=None
    ldap_user=None
    ldap_user_password=None
    ldap_fqdn=None
    openshift_sdn=None
    containerized=None
    container_storage=None
    openshift_disable_check=None
    wildcard_zone=None
    inventory_file='infrastructure.json'
    vmware_ini_path=None
    clean=None
    vm_ipaddr_allocation_type=None,
    cns_automation_config_file_path=None,
    docker_registry_url=None
    docker_additional_registries=None
    docker_insecure_registries=None
    docker_image_tag=None
    ose_puddle_repo=None
    gluster_puddle_repo=None
    web_console_install=None
    disable_yum_update_and_reboot=None

    def __init__(self, load=True):
        if load:
            self._parse_cli_args()
            self._read_ini_settings()
            self._check_ocp_vars()
        if not os.path.exists(self.inventory_file) or self.args.create_inventory:
            if self.no_confirm:
                self._create_inventory_file()
            else:
                if click.confirm('Overwrite the existing inventory file?'):
                    self._create_inventory_file()
        if (self.args.create_ocp_vars or
                "load_balancer_hostname:" in self.lb_config or
                self.vm_ipaddr_allocation_type == 'dhcp'):
            if self.no_confirm:
                self._create_ocp_vars()
            else:
                if click.confirm('Update the OCP install variables?'):
                    self._create_ocp_vars()
        if os.path.exists(self.inventory_file):
            self._launch_refarch_env()

    def _check_ocp_vars(self):
        ''' Check to see if the OCP vars have been changed'''
        for line in fileinput.input("playbooks/ocp-install.yaml"):
            loadbalancer = line.strip()
            if not loadbalancer.endswith("load_balancer_hostname:"):
                continue
            self.lb_config = loadbalancer

    def _parse_cli_args(self):
        ''' Command line argument processing '''
        tag_help = '''Skip to various parts of install valid tags include:
        - setup                     create the vCenter folder and resource pool
        - nfs                       create and setup the NFS VM
        - prod                      create and setup the OCP cluster
        - haproxy                   create and setup the haproxy VM
        - ocp-install               install OCP on the prod VMs
        - ocp-config                configure OCP on the prod VMs
        - ocp-demo                  test the OCP cluster
        - ocp-update                perform a minor update to OCP
        - clean                     unsubscribe and remove all VMs'''
        parser = argparse.ArgumentParser(description='Deploy VMs to vSphere and install/configure OCP', formatter_class=RawTextHelpFormatter)
        parser.add_argument('--clean', action='store_true', help='Delete all nodes and unregister from RHN')
        parser.add_argument('--create_inventory', action='store_true', help='Helper script to create json inventory file')
        parser.add_argument('--create_ocp_vars', action='store_true', help='Helper script to modify OpenShift ansible install variables')
        parser.add_argument('--no_confirm', action='store_true', help='Skip confirmation prompt')
        parser.add_argument('--tag', default=None, help=tag_help)
        parser.add_argument('--verbose', default=None, action='store_true', help='Verbosely display commands')
        self.args = parser.parse_args()
        self.verbose = self.args.verbose
        self.tag = self.args.tag
        self.no_confirm = self.args.no_confirm
        self.clean = self.args.clean

    def _is_rpm_and_image_tag_compatible(self):
        if not (self.docker_image_tag and self.ose_puddle_repo):
            return True
        url = self.ose_puddle_repo
        if url[-1] == '/':
            url += 'Packages/'
        else:
            url += '/Packages/'
        resp = requests.get(url)
        if resp.ok:
            v = self.docker_image_tag.split('v')[-1].strip()
            return (('atomic-openshift-%s' % v) in resp.text)
        raise Exception(
            "Failed to pull list of packages from '%s' url." % url)

    def _read_ini_settings(self):
        ''' Read ini file settings '''

        scriptbasename = "ocp-on-vmware"
        defaults = {'vmware': {
            'ini_path': os.path.join(os.path.dirname(__file__), '%s.ini' % scriptbasename),
            'console_port':'8443',
            'container_storage':'none',
            'deployment_type':'openshift-enterprise',
            'openshift_vers':'v3_6',
            'vcenter_username':'administrator@vsphere.local',
            'vcenter_template_name':'ocp-server-template-2.0.2',
            'vcenter_folder':'ocp',
            'vcenter_resource_pool':'/Resources/OCP3',
            'app_dns_prefix':'apps',
            'vm_network':'VM Network',
            'vm_ipaddr_allocation_type': 'static',
            'cns_automation_config_file_path': '',
            'docker_registry_url': '',
            'docker_additional_registries': '',
            'docker_insecure_registries': '',
            'docker_image_tag': '',
            'web_console_install': '',
            'ose_puddle_repo': '',
            'gluster_puddle_repo': '',
            'rhel_subscription_pool':'Red Hat OpenShift Container Platform, Premium*',
            'openshift_sdn':'redhat/openshift-ovs-subnet',
            'byo_lb':'False',
            'lb_host':'haproxy-',
            'byo_nfs':'False',
            'nfs_host':'nfs-0',
            'nfs_registry_mountpoint':'/exports',
            'master_nodes':'3',
            'infra_nodes':'2',
            'app_nodes':'3',
            'ocp_hostname_prefix':'',
            'auth_type':'ldap',
            'ldap_user':'openshift',
            'ldap_user_password':'',
            'tag': self.tag,
            'ldap_fqdn': '',
            'openshift_disable_check': (
                'docker_storage,docker_image_availability,disk_availability'),
            'disable_yum_update_and_reboot': 'no',
        }}
        if six.PY3:
            config = configparser.ConfigParser()
        else:
            config = configparser.SafeConfigParser()

        # where is the config?
        self.vmware_ini_path = os.environ.get('VMWARE_INI_PATH', defaults['vmware']['ini_path'])
        self.vmware_ini_path = os.path.expanduser(os.path.expandvars(self.vmware_ini_path))
        config.read(self.vmware_ini_path)

        # apply defaults
        for k,v in defaults['vmware'].iteritems():
            if not config.has_option('vmware', k):
                config.set('vmware', k, str(v))

        self.console_port = config.get('vmware', 'console_port')
        self.cluster_id = config.get('vmware', 'cluster_id')
        self.container_storage = config.get('vmware', 'container_storage')
        self.deployment_type = config.get('vmware','deployment_type')
        if os.environ.get('VIRTUAL_ENV'):
            self.openshift_vers = (
                'v3_%s' % os.environ['VIRTUAL_ENV'].split('_')[-1].split('.')[-1])
        else:
            self.openshift_vers = config.get('vmware','openshift_vers')
        self.vcenter_host = config.get('vmware', 'vcenter_host')
        self.vcenter_username = config.get('vmware', 'vcenter_username')
        self.vcenter_password = config.get('vmware', 'vcenter_password')
        self.vcenter_template_name = config.get('vmware', 'vcenter_template_name')
        self.vcenter_folder = config.get('vmware', 'vcenter_folder')
        self.vcenter_datastore = config.get('vmware', 'vcenter_datastore')
        self.vcenter_datacenter = config.get('vmware', 'vcenter_datacenter')
        self.vcenter_cluster = config.get('vmware', 'vcenter_cluster')
        self.vcenter_datacenter = config.get('vmware', 'vcenter_datacenter')
        self.vcenter_resource_pool = config.get('vmware', 'vcenter_resource_pool')
        self.dns_zone= config.get('vmware', 'dns_zone')
        self.app_dns_prefix = config.get('vmware', 'app_dns_prefix')
        self.vm_dns = config.get('vmware', 'vm_dns')
        self.vm_gw = config.get('vmware', 'vm_gw')
        self.vm_netmask = config.get('vmware', 'vm_netmask')
        self.vm_network = config.get('vmware', 'vm_network')
        self.vm_ipaddr_allocation_type = config.get('vmware', 'vm_ipaddr_allocation_type')
        self.cns_automation_config_file_path = config.get(
            'vmware', 'cns_automation_config_file_path')
        self.docker_registry_url = (
            config.get('vmware', 'docker_registry_url') or '').strip()
        self.docker_additional_registries = config.get(
            'vmware', 'docker_additional_registries')
        self.docker_insecure_registries = config.get(
            'vmware', 'docker_insecure_registries')
        self.docker_image_tag = (
            config.get('vmware', 'docker_image_tag') or '').strip()
        self.web_console_install = (
            config.get('vmware', 'web_console_install') or '').strip()
        self.ose_puddle_repo = config.get('vmware', 'ose_puddle_repo')
        self.gluster_puddle_repo = config.get('vmware', 'gluster_puddle_repo')
        self.rhel_subscription_user = config.get('vmware', 'rhel_subscription_user')
        self.rhel_subscription_pass = config.get('vmware', 'rhel_subscription_pass')
        self.rhel_subscription_server = config.get('vmware', 'rhel_subscription_server')
        self.rhel_subscription_pool = config.get('vmware', 'rhel_subscription_pool')
	self.rhsm_katello_url = config.get('vmware', 'rhsm_katello_url')
	self.rhsm_activation_key = config.get('vmware', 'rhsm_activation_key')
	self.rhsm_org_id = config.get('vmware', 'rhsm_org_id')
        self.openshift_sdn = config.get('vmware', 'openshift_sdn')
        self.byo_lb = config.get('vmware', 'byo_lb')
        self.lb_host = config.get('vmware', 'lb_host')
        self.lb_ha_ip = config.get('vmware', 'lb_ha_ip')
        self.byo_nfs = config.get('vmware', 'byo_nfs')
        self.nfs_host = config.get('vmware', 'nfs_host')
        self.nfs_registry_mountpoint = config.get('vmware', 'nfs_registry_mountpoint')
        self.master_nodes = config.get('vmware', 'master_nodes')
        self.infra_nodes = config.get('vmware', 'infra_nodes')
        self.app_nodes = config.get('vmware', 'app_nodes')
        self.storage_nodes = config.get('vmware', 'storage_nodes')
        self.vm_ipaddr_start = config.get('vmware', 'vm_ipaddr_start')
        self.vm_ipaddr_allocation_type = config.get('vmware', 'vm_ipaddr_allocation_type')
        self.ocp_hostname_prefix = config.get('vmware', 'ocp_hostname_prefix') or ''
        self.auth_type = config.get('vmware', 'auth_type')
        self.ldap_user = config.get('vmware', 'ldap_user')
        self.ldap_user_password = config.get('vmware', 'ldap_user_password')
        self.ldap_fqdn = config.get('vmware', 'ldap_fqdn')
        self.openshift_disable_check = config.get(
            'vmware', 'openshift_disable_check').strip() or (
                'docker_storage,docker_image_availability,disk_availability')
        self.disable_yum_update_and_reboot = config.get(
            'vmware', 'disable_yum_update_and_reboot').strip() or 'no'
        err_count=0

        required_vars = {
            'dns_zone': self.dns_zone,
            'vcenter_host': self.vcenter_host,
            'vcenter_password': self.vcenter_password,
            'vm_ipaddr_start': self.vm_ipaddr_start,
            'vm_ipaddr_allocation_type': self.vm_ipaddr_allocation_type,
            'ldap_fqdn': self.ldap_fqdn,
            'ldap_user_password': self.ldap_user_password,
            'vm_dns': self.vm_dns,
            'vm_gw': self.vm_gw,
            'vm_netmask': self.vm_netmask,
            'vcenter_datacenter': self.vcenter_datacenter,
        }

        for k, v in required_vars.items():
            if v == '':
                err_count += 1
                print "Missing %s " % k
        if required_vars['vm_ipaddr_allocation_type'] not in ('dhcp', 'static'):
            err_count += 1
            print ("'vm_ipaddr_allocation_type' can take only "
                   "'dhcp' and 'static' values.")
        if (self.cns_automation_config_file_path and
                not os.path.exists(
                    os.path.abspath(self.cns_automation_config_file_path))):
            err_count += 1
            print ("Wrong value for 'cns_automation_config_file_path' "
                   "config option. It is expected to be either a relative "
                   "or an absolute file path.")
        else:
            self.cns_automation_config_file_path = os.path.abspath(
                self.cns_automation_config_file_path)
        if self.docker_image_tag and self.docker_registry_url:
            vers_from_reg = self.docker_registry_url.split(':')[-1].strip()
            if not vers_from_reg == self.docker_image_tag:
                err_count += 1
                print ("If 'docker_image_tag' and 'docker_registry_url' are "
                       "specified, then their image tags should match. "
                       "docker_image_tag='%s', docker_registry_url='%s'" % (
                           self.docker_image_tag, self.docker_registry_url))
        if not self._is_rpm_and_image_tag_compatible():
            err_count += 1
            print ("OCP RPM versions and docker image tag do not match. "
                   "Need either to change 'ose_puddle_repo' or "
                   "'docker_image_tag' config options.")
        allowed_disable_checks = (
            'disk_availability',
            'docker_image_availability',
            'docker_storage',
            'memory_availability',
            'package_availability',
            'package_version',
        )
        self.openshift_disable_check_data = [
            el.strip()
            for el in self.openshift_disable_check.strip().split(',')
            if el.strip()
        ]
        if not all([(s in allowed_disable_checks)
                    for s in self.openshift_disable_check_data]):
            err_count += 1
            print ("'openshift_disable_check' is allowed to have only "
                   "following values separated with comma: %s.\n "
                   "Got following value: %s" % (','.join(
                       allowed_disable_checks), self.openshift_disable_check))

        if err_count > 0:
            print "Please fill out the missing variables in %s " %  self.vmware_ini_path
            exit (1)
        self.wildcard_zone="%s.%s" % (self.app_dns_prefix, self.dns_zone)
        self.support_nodes=0

        if not self.cluster_id:
        #create a unique cluster_id first
            self.cluster_id = ''.join(random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for i in range(7))
            config.set('vmware', 'cluster_id', self.cluster_id)
            for line in fileinput.input(self.vmware_ini_path, inplace=True):
                if line.startswith('cluster_id'):
                    print "cluster_id=" + str(self.cluster_id)
                else:
                    print line,

        print 'Configured inventory values:'
        for each_section in config.sections():
            for (key, val) in config.items(each_section):
                if 'pass' in key:
                    print '\t %s:  ******' % ( key )
                else:
                    print '\t %s:  %s' % ( key,  val )
        print '\n'

    def _create_inventory_file(self):
        click.echo('Configured inventory values:')
        click.echo('\tmaster_nodes: %s' % self.master_nodes)
        click.echo('\tinfra_nodes: %s' % self.infra_nodes)
        click.echo('\tapp_nodes: %s' % self.app_nodes)
        click.echo('\tdns_zone: %s' % self.dns_zone)
        click.echo('\tapp_dns_prefix: %s' % self.app_dns_prefix)
        click.echo('\tocp_hostname_prefix: %s' % self.ocp_hostname_prefix)
        click.echo('\tbyo_nfs: %s' % self.byo_nfs)
        if self.byo_nfs == "False":
            click.echo('\tnfs_host: %s' % self.nfs_host)
        click.echo('\tbyo_lb: %s' % self.byo_lb)
        if self.byo_lb == "False":
            click.echo('\tlb_host: %s' % self.lb_host)
        click.echo('\tvm_ipaddr_start: %s' % self.vm_ipaddr_start)
        click.echo('\tvm_ipaddr_allocation_type: %s' % self.vm_ipaddr_allocation_type)
        click.echo('\tUsing values from: %s' % self.vmware_ini_path)
        click.echo("")
        if not self.no_confirm:
            click.confirm('Continue using these values?', abort=True)

        if self.byo_nfs == "False":
            self.support_nodes=self.support_nodes+1
        if self.byo_lb == "False":
            if self.lb_ha_ip != '':
                self.support_nodes=self.support_nodes+3
            else:
                self.support_nodes=self.support_nodes+1
        total_nodes=int(self.master_nodes)+int(self.app_nodes)+int(self.infra_nodes)+int(self.support_nodes)
        ip4addr = []
        for i in range(total_nodes):
            p = iptools.ipv4.ip2long(self.vm_ipaddr_start) + i
            ip4addr.append(iptools.ipv4.long2ip(p))
        wild_ip =  ip4addr.pop()
        # Pop out the last address for the haproxy to use

        bind_entry = []
        bind_entry.append("$ORIGIN " + self.app_dns_prefix + "." + self.dns_zone + ".")
        bind_entry.append("*\t\tA\t" + wild_ip)
        bind_entry.append("$ORIGIN " + self.dns_zone + ".")

        d = {}
        d['host_inventory'] = {}

        if self.byo_nfs == "False" and False:
            if self.ocp_hostname_prefix not in self.nfs_host:
                nfs_entry = "%s-%s" % (self.ocp_hostname_prefix, self.nfs_host)
            else:
                nfs_entry = self.nfs_host
            d['host_inventory'][nfs_entry] = {}
            d['host_inventory'][nfs_entry]['guestname'] = nfs_entry
            d['host_inventory'][nfs_entry]['guesttype'] = 'nfs'
            d['host_inventory'][nfs_entry]['vm_ipaddr_allocation_type'] = (
                self.vm_ipaddr_allocation_type)
            d['host_inventory'][nfs_entry]['ip4addr'] = ip4addr[0]
            d['host_inventory'][nfs_entry]['tag'] = str(self.cluster_id) + "-networkfs"
            bind_entry.append(nfs_entry + "\t\tA\t" + ip4addr[0])
            del ip4addr[0]

        if self.byo_lb == "False" and int(self.master_nodes) > 1:
            if self.lb_ha_ip:
                bind_entry.append(self.lb_ha_ip + "\t\tA\t" + wild_ip)
                i = 2
            else:
                i = 1
            for i in range(0, int(i)):
                lb_name = "%s-haproxy-%d" % (self.ocp_hostname_prefix, i)
                d['host_inventory'][lb_name] = {}
                d['host_inventory'][lb_name]['guestname'] = lb_name
                d['host_inventory'][lb_name]['guesttype'] = 'haproxy'
                d['host_inventory'][lb_name]['vm_ipaddr_allocation_type'] = (
                self.vm_ipaddr_allocation_type)
                if not self.lb_ha_ip:
                    d['host_inventory'][lb_name]['ip4addr'] = wild_ip
                    bind_entry.append(lb_name + "\tA\t" + wild_ip)
                else:
                    d['host_inventory'][lb_name]['ip4addr'] = ip4addr[0]
                    bind_entry.append(lb_name + "\tA\t" + str(ip4addr[0]))
                    del ip4addr[0]
                d['host_inventory'][lb_name]['tag'] =  str(self.cluster_id) + "-loadbalancer"

        for i in range(0, int(self.master_nodes)):
            master_name = "%s-master-%d" % (self.ocp_hostname_prefix, i)
            d['host_inventory'][master_name] = {}
            d['host_inventory'][master_name]['guestname'] = master_name
            d['host_inventory'][master_name]['guesttype'] = 'master'
            d['host_inventory'][master_name]['vm_ipaddr_allocation_type'] = (
                self.vm_ipaddr_allocation_type)
            d['host_inventory'][master_name]['ip4addr'] = ip4addr[0]
            d['host_inventory'][master_name]['tag'] = str(self.cluster_id) + '-master'
            bind_entry.append(master_name + "\tA\t" + ip4addr[0])
            del ip4addr[0]

        for i in range(0, int(self.app_nodes)):
            app_name = "%s-app-%d" % (self.ocp_hostname_prefix, i)
            d['host_inventory'][app_name] = {}
            d['host_inventory'][app_name]['guestname'] = app_name
            d['host_inventory'][app_name]['guesttype'] = 'app'
            d['host_inventory'][app_name]['vm_ipaddr_allocation_type'] = (
                self.vm_ipaddr_allocation_type)
            d['host_inventory'][app_name]['ip4addr'] = ip4addr[0]
            d['host_inventory'][app_name]['tag'] = str(self.cluster_id) + '-app'
            bind_entry.append(app_name + "\t\tA\t" + ip4addr[0])
            del ip4addr[0]

        for i in range(0, int(self.infra_nodes)):
            infra_name = "%s-infra-%d" % (self.ocp_hostname_prefix, i)
            d['host_inventory'][infra_name] = {}
            d['host_inventory'][infra_name]['guestname'] = infra_name
            d['host_inventory'][infra_name]['guesttype'] = 'infra'
            d['host_inventory'][infra_name]['vm_ipaddr_allocation_type'] = (
                self.vm_ipaddr_allocation_type)
            d['host_inventory'][infra_name]['ip4addr'] = ip4addr[0]
            d['host_inventory'][infra_name]['tag'] = str(self.cluster_id) + '-infra'
            bind_entry.append(infra_name + "\t\tA\t" + ip4addr[0])
            del ip4addr[0]

        print "# Here is what should go into your DNS records"
        print("\n".join(bind_entry))
        print "# Please note, if you have chosen to bring your own loadbalancer and NFS Server you will need to ensure that these records are added to DNS and properly resolve. "

        with open(self.inventory_file, 'w') as outfile:
            json.dump(d, outfile, indent=4, sort_keys=True)

        if self.args.create_inventory:
            exit(0)

    def _create_ocp_vars(self):
        click.echo('Configured OCP variables:')
        click.echo('\tauth_type: %s' % self.auth_type)
        click.echo('\tldap_fqdn: %s' % self.ldap_fqdn)
        click.echo('\tldap_user: %s' % self.ldap_user)
        click.echo('\tldap_user_password: %s' % self.ldap_user_password)
        click.echo('\tdns_zone: %s' % self.dns_zone)
        click.echo('\tapp_dns_prefix: %s' % self.app_dns_prefix)
        click.echo('\tbyo_lb: %s' % self.byo_lb)
        if self.lb_ha_ip:
            click.echo('\tlb_ha_ip: %s' % self.lb_ha_ip)
        else:
            click.echo('\tlb_host: %s' % self.lb_host)
        click.echo('\tUsing values from: %s' % self.vmware_ini_path)
        if not self.no_confirm:
            click.confirm('Continue using these values?', abort=True)

        install_file = "playbooks/ocp-install.yaml"

        # NOTE(vponomar): following cycle is dead code while we do not add
        # support for nfs node back again.
        for line in fileinput.input(install_file, inplace=True):
            if line.startswith("    openshift_hosted_registry_storage_host:"):
                print ("    openshift_hosted_registry_storage_host: " +
                       self.nfs_host + "." + self.dns_zone)
            elif line.startswith("    openshift_hosted_registry_storage_nfs_directory:"):
                print ("    openshift_hosted_registry_storage_nfs_directory: " +
                       self.nfs_registry_mountpoint)
            elif line.startswith("    openshift_hosted_metrics_storage_host:"):
                print ("    openshift_hosted_metrics_storage_host: " +
                       self.nfs_host + "." + self.dns_zone)
            elif line.startswith("    openshift_hosted_metrics_storage_nfs_directory:"):
                print ("    openshift_hosted_metrics_storage_nfs_directory: " +
                       self.nfs_registry_mountpoint)
            else:
                print line,

        update_file = "playbooks/minor-update.yaml"
        if int(self.master_nodes) < 2:
            self.lb_host = '%s-master-0' % self.ocp_hostname_prefix

        if self.auth_type == 'none':
            for line in fileinput.input(install_file, inplace=True):
                if line.startswith('#openshift_master_identity_providers:'):
                    line = line.replace('#', '    ')
                    print line
                else:
                    print line,
        elif self.auth_type == 'ldap':
            l_bdn = ""

            for d in self.ldap_fqdn.split("."):
                l_bdn = l_bdn + "dc=" + d + ","

            l = ldap.initialize("ldap://" + self.ldap_fqdn)
            try:
                l.protocol_version = ldap.VERSION3
                l.set_option(ldap.OPT_REFERRALS, 0)
                bind = l.simple_bind_s(self.ldap_user, self.ldap_user_password)

                base = l_bdn[:-1]
                criteria = "(&(objectClass=user)(sAMAccountName=" + self.ldap_user + "))"
                attributes = 'displayName', 'distinguishedName'
                result = l.search_s(base, ldap.SCOPE_SUBTREE, criteria, attributes)

                results = [entry for dn, entry in result if isinstance(entry, dict)]
            finally:
                l.unbind()

            for result in results:
                bindDN = str(result['distinguishedName']).strip("'[]")
                url_base = bindDN.replace(("CN=" + self.ldap_user + ","), "")
                url = "ldap://" + self.ldap_fqdn + ":389/" + url_base + "?sAMAccountName"

            for line in fileinput.input(install_file, inplace=True):
            # Parse our ldap url
                if line.startswith("      url:"):
                    print "      url: " + url
                elif line.startswith("      bindPassword:"):
                    print "      bindPassword: " + self.ldap_user_password
                elif line.startswith("      bindDN:"):
                    print "      bindDN: " + bindDN
                else:
                    print line,

        else:
            print ("'auth_type' configuration has improper value '%s'. "
                   "It is allowed to be either "
                   "'ldap' or 'none'." % self.auth_type)
            exit(1)
        if self.args.create_ocp_vars:
            exit(0)

    def _launch_refarch_env(self):
        with open(self.inventory_file, 'r') as f:
            print yaml.safe_dump(json.load(f), default_flow_style=False)

        if not self.args.no_confirm:
            if not click.confirm('Continue adding nodes with these values?'):
                sys.exit(0)

        # Add section here to modify inventory file based on input from user check your vmmark scripts for parsing the file and adding the values
        for line in fileinput.input("inventory/vsphere/vms/vmware_inventory.ini", inplace=True):
            if line.startswith("server="):
                print "server=" + self.vcenter_host
            elif line.startswith("password="):
                print "password=" + self.vcenter_password
            elif line.startswith("username="):
                print "username=" + self.vcenter_username
            else:
                print line,

        if self.clean is True:
            tags = 'clean'
        elif self.tag:
            tags = self.tag
        else:
            tags = ['setup']

            # TODO(vponomar): make it configurable
            if self.byo_nfs == "False" and False:
                tags.append('nfs')

            tags.append('prod')

            # TODO(vponomar): update it when we support haproxy
            if self.byo_lb == "False" and False:
                tags.append('haproxy')

            tags.append('ocp-install')
            tags.append('ocp-configure')
            tags = ",".join(tags)

        # remove any cached facts to prevent stale data during a re-run
        command='rm -rf .ansible/cached_facts'
        os.system(command)

        playbook_vars_dict = {
            'vcenter_host': self.vcenter_host,
            'vcenter_username': self.vcenter_username,
            'vcenter_password': self.vcenter_password,
            'vcenter_template_name': self.vcenter_template_name,
            'vcenter_folder': self.vcenter_folder,
            'vcenter_cluster': self.vcenter_cluster,
            'vcenter_datacenter': self.vcenter_datacenter,
            'vcenter_datastore': self.vcenter_datastore,
            'vcenter_resource_pool': self.vcenter_resource_pool,
            'dns_zone': self.dns_zone,
            'app_dns_prefix': self.app_dns_prefix,
            'vm_dns': self.vm_dns,
            'vm_gw': self.vm_gw,
            'vm_netmask': self.vm_netmask,
            'vm_network': self.vm_network,
            'vm_ipaddr_allocation_type': self.vm_ipaddr_allocation_type,
            'cns_automation_config_file_path': (
                self.cns_automation_config_file_path),
            'ose_puddle_repo': self.ose_puddle_repo,
            'gluster_puddle_repo': self.gluster_puddle_repo,
            'wildcard_zone': self.wildcard_zone,
            'console_port': self.console_port,
            'cluster_id': self.cluster_id,
            'deployment_type': self.deployment_type,
            'openshift_vers': self.openshift_vers,
            'rhsm_user': self.rhel_subscription_user,
            'rhsm_password': self.rhel_subscription_pass,
            'rhsm_satellite': self.rhel_subscription_server,
            'rhsm_pool': self.rhel_subscription_pool,
            'rhsm_katello_url': self.rhsm_katello_url,
            'rhsm_activation_key': self.rhsm_activation_key,
            'rhsm_org_id': self.rhsm_org_id,
            'openshift_sdn': self.openshift_sdn,
            'openshift_use_openshift_sdn': True,
            'containerized': self.containerized,
            'container_storage': self.container_storage,
            'lb_host': self.lb_host,
            'lb_ha_ip': self.lb_ha_ip,
            'ocp_hostname_prefix': self.ocp_hostname_prefix,
            'nfs_host': self.nfs_host,
            'nfs_registry_mountpoint': self.nfs_registry_mountpoint,
            'disable_yum_update_and_reboot': self.disable_yum_update_and_reboot
        }
        if self.openshift_disable_check_data:
            playbook_vars_dict["openshift_disable_check"] = (
                ','.join(self.openshift_disable_check_data))
        if self.docker_registry_url:
            playbook_vars_dict['oreg_url'] = self.docker_registry_url
        if self.docker_additional_registries:
            playbook_vars_dict['openshift_docker_additional_registries'] = (
                self.docker_additional_registries)
            playbook_vars_dict['openshift_docker_ent_reg'] = ''
        if self.docker_insecure_registries:
            playbook_vars_dict['openshift_docker_insecure_registries'] = (
                self.docker_insecure_registries)
        if self.docker_image_tag:
            playbook_vars_dict['openshift_image_tag'] = self.docker_image_tag
        if self.web_console_install:
            playbook_vars_dict['openshift_web_console_install'] = (
                self.web_console_install)
        if self.openshift_vers in ('v3_6', 'v3_7'):
            playbook_vars_dict['docker_version'] = '1.12.6'

        playbook_vars_str = ' '.join('%s=%s' % (k, v)
                                     for (k, v) in playbook_vars_dict.items())

        command = (
            "ansible-playbook"
            " --extra-vars '@./infrastructure.json'"
            " --tags %s"
            " -e '%s' playbooks/ocp-end-to-end.yaml"
        ) % (tags, playbook_vars_str)

        if self.verbose > 0:
            command += " -vvvvvv"

        click.echo('We are running: %s' % command)
        status = os.system(command)
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
            sys.exit(os.WEXITSTATUS(status))


if __name__ == '__main__':
    VMwareOnOCP()
