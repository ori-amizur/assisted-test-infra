import logging
import json
from typing import Dict, Iterator, List
import random

import waiting
from munch import Munch
from test_infra.controllers.node_controllers.node_controller import NodeController
from test_infra import utils
from tests.conftest import env_variables
from test_infra.controllers.node_controllers.node import Node
from test_infra.tools.concurrently import run_concurrently


class NodeMapping:
    def __init__(self, node, cluster_host):
        self.name = node.name
        self.node = node
        self.cluster_host = cluster_host


class Nodes:
    def __init__(self, node_controller: NodeController, private_ssh_key_path):
        self.controller = node_controller
        self.private_ssh_key_path = private_ssh_key_path
        self._nodes = None
        self._nodes_as_dict = None

    @property
    def nodes(self) -> List[Node]:
        if not self._nodes:
            self._nodes = self._list()
        return self._nodes

    def __getitem__(self, i):
        return self.nodes[i]

    def __len__(self):
        return len(self.nodes)

    def __iter__(self) -> Iterator[Node]:
        for n in self.nodes:
            yield n

    def get_masters(self):
        return [node for node in self.nodes if node.is_master_in_name()]

    @property
    def nodes_as_dict(self):
        if not self._nodes_as_dict:
            self._nodes_as_dict = {node.name: node for node in self.nodes}
        return self._nodes_as_dict

    def _list(self):
        nodes = self.controller.list_nodes()
        return [Node(node.name(), self.controller, self.private_ssh_key_path) for node in nodes]

    @property
    def setup_time(self):
        return self.controller.setup_time

    def get_random_node(self):
        return random.choice(self.nodes)

    def shutdown_all(self):
        self.run_for_all_nodes("shutdown")

    def start_all(self):
        self.run_for_all_nodes("start")

    def start_given(self, nodes):
        self.run_for_given_nodes(nodes, "start")

    def shutdown_given(self, nodes):
        self.run_for_given_nodes(nodes, "shutdown")

    def format_all_disks(self):
        self.run_for_all_nodes("format_disk")

    def destroy_all(self):
        self.run_for_all_nodes("shutdown")

    def destroy_all_nodes(self):
        self.controller.destroy_all_nodes()

    def prepare_nodes(self):
        self.controller.prepare_nodes()

    def reboot_all(self):
        self.run_for_all_nodes("restart")

    def reboot_given(self, nodes):
        self.run_for_given_nodes(nodes, "restart")

    def get_cluster_network(self):
        return self.controller.get_cluster_network()

    def set_correct_boot_order(self, nodes=None, start_nodes=False):
        nodes = nodes or self.nodes
        logging.info("Going to set correct boot order to nodes: %s", nodes)
        self.run_for_given_nodes(nodes, "set_boot_order_flow", False, start_nodes)

    def run_for_all_nodes(self, func_name, *args):
        return self.run_for_given_nodes(self.nodes, func_name, *args)

    @staticmethod
    def run_for_given_nodes(nodes, func_name, *args):
        logging.info("Running %s on nodes : %s", func_name, nodes)
        return run_concurrently([(getattr(node, func_name), *args) for node in nodes])

    def run_for_given_nodes_by_cluster_hosts(self, cluster_hosts, func_name, *args):
        return self.run_for_given_nodes([self.get_node_from_cluster_host(host) for
                                         host in cluster_hosts], func_name, *args)

    @staticmethod
    def run_ssh_command_on_given_nodes(nodes, command) -> Dict:
        return run_concurrently({node.name: (node.run_command, command) for node in nodes})

    def set_wrong_boot_order(self, nodes=None, start_nodes=True):
        nodes = nodes or self.nodes
        logging.info("Setting wrong boot order for %s", self.nodes_as_dict.keys())
        self.run_for_given_nodes(nodes, "set_boot_order_flow", True, start_nodes)

    def get_bootstrap_node(self, cluster) -> Node:
        for cluster_host_object in cluster.get_hosts():
            if cluster_host_object.get("bootstrap", False):
                node = self.get_node_from_cluster_host(cluster_host_object)
                logging.info("Bootstrap node is %s", node.name)
                return node

    def create_nodes_cluster_hosts_mapping(self, cluster):
        node_mapping_dict = {}
        for cluster_host_object in cluster.get_hosts():
            name = self.get_cluster_hostname(cluster_host_object)
            node_mapping_dict[name] = NodeMapping(self.nodes_as_dict[name],
                                                                             Munch.fromDict(cluster_host_object))
        return node_mapping_dict

    def get_node_from_cluster_host(self, cluster_host_object):
        hostname = self.get_cluster_hostname(cluster_host_object)
        return self.get_node_by_hostname(hostname)

    def get_node_by_hostname(self, get_node_by_hostname):
        return self.nodes_as_dict[get_node_by_hostname]

    def get_cluster_host_obj_from_node(self, cluster, node):
        mapping = self.create_nodes_cluster_hosts_mapping(cluster=cluster)
        return mapping[node.name].cluster_host

    def get_cluster_hostname(self, cluster_host_object):
        inventory = json.loads(cluster_host_object["inventory"])
        return inventory["hostname"]

    def set_hostnames(self, cluster):
        ipv6 = env_variables.get('ipv6')
        if ipv6:
            # When using IPv6 with libvirt, hostnames are not set automatically by DHCP.  Therefore, we must find out
            # the hostnames using terraform's tfstate file
            network_name = self.controller.params.libvirt_network_name
            libvirt_nodes = utils.get_libvirt_nodes_from_tf_state(network_name, self.controller.tf.get_state())
            utils.update_hosts(cluster.api_client, cluster.id, libvirt_nodes, update_hostnames=True)



