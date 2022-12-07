#!/bin/env python3

# This script parse Hermes configuration to extract registry informations
import argparse
import json
import os.path
from types import SimpleNamespace

import requests

import toml
import urllib3.util

import certifi
import cosmpy.protos.ibc.core.channel.v1.query_pb2_grpc
import cosmpy.protos.ibc.core.connection.v1.query_pb2_grpc
import cosmpy.protos.ibc.core.client.v1.query_pb2_grpc
import grpc

from cosmpy.protos.ibc.core.channel.v1.channel_pb2 import Channel
from cosmpy.protos.ibc.core.channel.v1.query_pb2 import QueryChannelRequest
from cosmpy.protos.ibc.core.connection.v1.connection_pb2 import ConnectionEnd
from cosmpy.protos.ibc.core.connection.v1.query_pb2 import QueryConnectionRequest
from cosmpy.protos.ibc.core.client.v1.query_pb2 import QueryClientStateRequest
from google.protobuf.json_format import MessageToJson


class ChainChain:
    """
    This class build configuration file.
    """
    def __init__(self, chain1_name, chain2_name):
        """

        :param chain1_name: first chain name
        :param chain2_name: second chain name
        """
        self.chain2 = None
        self.chain1 = None
        self.chain1_name = chain1_name
        self.chain2_name = chain2_name

    def populate_chain_1(self, chain_id:str, channel:str, wallet:str, version='ics20-1'):
        """
        fill parameter for the first chain

        :param chain_id: chain_id
        :param channel: IBC channel
        :param wallet: relayer wallet
        :param version: channel ics version
        :return: None
        """
        self.chain1 = {
            "address": wallet,
            "chain-id": chain_id,
            "channel-id": channel,
            "version": version
        }
    
    def populate_chain_2(self, chain_id:str, channel:str, wallet:str, version='ics20-1'):
        """
        fill parameter for the second chain

        :param chain_id: chain_id
        :param channel: IBC channel
        :param wallet: relayer wallet
        :param version: channel ics version
        :return: None
        """
        self.chain2 = {
            "address": wallet,
            "chain-id": chain_id,
            "channel-id": channel,
            "version": version
        }
    
    def chain_couple(self) -> dict:
        return {
            self.chain1['chain-id']: self.chain1['address'],
            self.chain2['chain-id']: self.chain2['address'],
        }
    def to_string(self) -> str:
        """
        Convert configuration to string
        :return: str
        """
        return json.dumps({
            self.chain1['chain-id']: self.chain1['address'],
            self.chain2['chain-id']: self.chain2['address'],
        }, indent=4, separators=(", ", ": "))
    
    def write_as_file(self, path='.', suffix=''):
        """
        Write configuration to file
        :param path: file directory path
        :param suffix: optional suffix for file name
        :return: None
        """
        file_name = "{chain1}-{chain2}{suf}.json".format(chain1=self.chain1_name,
                                                         chain2=self.chain2_name,
                                                         suf=f"-{suffix}" if suffix else '')
        print(f"write {file_name}")
        full_path = os.path.join(path, file_name)
        print("mkdir {}".format(os.path.dirname(full_path)))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w+') as f:
            json.dump({"chain-1": self.chain1, "chain-2": self.chain2},
                      f, indent=4, separators=(", ", ": "))


class GrpcIBC:
    """
    This class allow the query of IBC information through IBC
    """
    def __init__(self, url: str):
        """
        initialize the GRPC client
        :param url: URL to GRPC server endpoint
        """
        self.grpc_url = urllib3.util.parse_url(url)
        self.grpc_client = None
        client_url = "{}:{}".format(urllib3.util.get_host(str(grpc_url))[1], urllib3.util.get_host(str(grpc_url))[2])
        print(f"connecting({client_url})")
        if 'https' in urllib3.util.get_host(str(grpc_url))[0]:
            with open(certifi.where(), "rb") as f:
                trusted_certs = f.read()
            credentials = grpc.ssl_channel_credentials(
                root_certificates=trusted_certs
            )
            self.grpc_client = grpc.secure_channel(client_url, credentials)
        else:
            self.grpc_client = grpc.insecure_channel(client_url)

        self.ibc_channel_query = cosmpy.protos.ibc.core.channel.v1.query_pb2_grpc.QueryStub(self.grpc_client)
        self.ibc_connection_query = cosmpy.protos.ibc.core.connection.v1.query_pb2_grpc.QueryStub(self.grpc_client)
        self.ibc_client_query = cosmpy.protos.ibc.core.client.v1.query_pb2_grpc.QueryStub(self.grpc_client)

    def query_channel(self, port:str, channel:str) -> Channel:
        """
        query IBC channel information
        :param port: port name
        :param channel: channel name
        :return: Channel object
        """
        resp = self.ibc_channel_query.Channel(QueryChannelRequest(port_id=port, channel_id=channel))
        return resp.channel

    def query_connection(self, connection:str) -> ConnectionEnd:
        """
        query IBC connection information
        :param connection: connection name
        :return: ConnectionEnd object
        """
        resp = self.ibc_connection_query.Connection(QueryConnectionRequest(connection_id=connection))
        return resp

    def query_client(self, client:str) -> dict:
        """
        query IBC client state
        :param client: IBC client name
        :return: dict representation of Client state object
        """
        from cosmpy.protos.ibc.lightclients.tendermint.v1.tendermint_pb2 import ClientState

        resp = self.ibc_client_query.ClientState(QueryClientStateRequest(client_id=client))
        # client_state is not parsed in the answer
        try:
            string_json = MessageToJson(resp.client_state)
        except TypeError as err:
            print(err)
        # Parse JSON into an object with attributes corresponding to dict keys.
        mess = json.loads(string_json, object_hook=lambda d: SimpleNamespace(**d))
        return mess


class Registry:
    """
    this class allow to query cosmos.directory
    """
    chain_registry = []

    def __init__(self):
        """
        """
        self.chain_registry = self.get_chains()

    def get_chains(self) -> dict:
        """
        Get all the chains referenced on cosmos.directory
        :return: dict
        """
        chains = requests.get("https://chains.cosmos.directory/").json()['chains']
        return chains

    def get_chain(self, chain:str) -> dict:
        """
        Get information for the provided chain
        :param chain: chain name to query
        :return: dict
        """
        try:
            if isinstance(chain, dict):
                chain_name: str = next(item for item in self.chain_registry if item["chain_id"] == chain['id'])['name']
            else:
                chain_name: str = next(item for item in self.chain_registry if item["chain_id"] == chain)['name']
            chain_def_full = requests.get("https://chains.cosmos.directory/{}".format(chain_name)).json()['chain']
        except StopIteration:
            print("chain {} not found in registry.".format(chain))
            raise
        return chain_def_full


def get_wallet_from_keyring(chain_id:str, key_name:str) -> str:
    """
    parse the Hermes keyring to extract wallet address
    :param chain_id: chaine_id
    :param key_name: key name
    :return: str
    """
    wallet: str = ""
    homedir = os.getenv("HOME")
    with open(f"{homedir}/.hermes/keys/{chain_id}/keyring-test/{key_name}.json", 'r') as f:
        wallet = json.load(f)['account']
    return wallet


def get_counterparty_chain(ibc:GrpcIBC, port:str, channel:str):
    """
    get all the counterparty information for an IBC channel
    :param ibc: initialized GrpcIBC object
    :param port: source port name
    :param channel: source channel name
    :return: tuple(chain_id, port, channel)
    """
    try:
        channel_resp = ibc.query_channel(port, channel)
    except grpc.RpcError as err:
        print("chain config {} not parsed, due to bad GRPC endpoint.".format(chain['id']))
        raise err
    counterparty_port: str = channel_resp.counterparty.port_id
    counterparty_channel: str = channel_resp.counterparty.channel_id
    connection = channel_resp.connection_hops[-1:][0]

    resp = ibc.query_connection(connection)
    client_id = resp.connection.client_id

    client = ibc.query_client(client_id)
    counterparty_chain_id: str = client.chainId
    return counterparty_chain_id, counterparty_port, counterparty_channel

def write_ccs(team_name, team_logo, team_website, team_github, team_twitter, team_discord, team_desc, ccs, path='.'):
    """
    Write configuration to file
    :param path: file directory path
    :param suffix: optional suffix for file name
    :return: None
    """
    if path == '.':
        dest_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 '..', "relayers", args.team_name, "relayer_info.json")
    else:
        dest_file = os.path.join(path, "relayers", args.team_name, "relayer_info.json")
    os.makedirs(os.path.dirname(os.path.abspath(dest_file)), exist_ok=True)
    full_file = {
        "team_name": team_name,
        "team_logo": team_logo,
        "contact":{
            "website": team_website,
            "github": team_github,
            "twitter": team_twitter,
            "discord": team_discord
        },
        "introduction":[
            team_desc
        ],
        "addresses": ccs
    }

    with open(dest_file, 'w+') as f:
        json.dump(full_file, f, indent=4, separators=(",", ": "))

if __name__ == '__main__':
    ccs = []
    parser = argparse.ArgumentParser(description='Read Hermes configuration and generate relayer registry entries')
    parser.add_argument('--config', type=str, default="{}/.hermes/config.toml".format(os.getenv('HOME')),
                        help='path the the hermes configuration file')
    parser.add_argument('--team_name', type=str, default='',
                        help='team name', required=True)
    parser.add_argument('--path', type=str, default='.',
                        help='path to store output files')
    parser.add_argument('--team_logo', type=str, default='',
                        help='team logo')
    parser.add_argument('--team_website', type=str, default='',
                        help='team website')
    parser.add_argument('--team_github', type=str, default='',
                        help='team github')
    parser.add_argument('--team_twitter', type=str, default='',
                        help='team twitter')
    parser.add_argument('--team_discord', type=str, default='',
                        help='team discord')
    parser.add_argument('--team_medium', type=str, default='',
                        help='team medium')
    parser.add_argument('--team_description', type=str, default='',
                        help='team description')
    args = parser.parse_args()

    if args.team_name != '':
        dest_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 '..', "relayers", args.team_name, "relayer_info.json")
        if os.path.exists(dest_file):
            existing_info = json.load(open(dest_file, 'r'))
            args.team_logo = existing_info["team_logo"] if args.team_logo == "" else args.team_logo
            args.team_website = existing_info["contact"].get("website","") if args.team_website == "" else args.team_website
            args.team_github = existing_info["contact"].get("github","") if args.team_github == "" else args.team_github
            args.team_twitter = existing_info["contact"].get("twitter","") if args.team_twitter == "" else args.team_twitter
            args.team_discord = existing_info["contact"].get("discord","") if args.team_discord == "" else args.team_discord
            args.team_medium = existing_info["contact"].get("medium","") if args.team_medium == "" else args.team_medium
            args.team_description = existing_info["introduction"][0] if args.team_description == "" else args.team_description
            ccs = existing_info["addresses"]
    registry = Registry()

    config = toml.load(open(args.config, 'r'))
    
    for chain in config['chains']:
        if 'packet_filter' not in chain:
            print("chain config {} not parsed, please use packet_filter.".format(chain['id']))
            continue
        if chain['packet_filter']['policy'] != 'allow':
            print("chain config {} not parsed, please use \'allow\' packet_filter\'s policy.".format(chain['id']))
            continue

        try:
            chain_extended_definition = registry.get_chain(chain)
        except StopIteration:
            print("chain {} not found in registry.".format(chain))
            continue

        chain_name = chain_extended_definition['name']
        chain_id = chain['id']
        port = ""
        channel = ""

        counterparty_chain_id = ""
        counterparty_port = ""
        counterparty_channel = ""

        # uncomment to use chain-registry GRPC endpoint. (note that many are not working)
        # grpc_url = urllib3.util.parse_url(chain_extended_definition['apis']['grpc'][0]['address'])
        # comment if using chain-registry GRPC endpoint
        grpc_url = urllib3.util.parse_url(chain['grpc_addr'])
        ibc = GrpcIBC(str(grpc_url))

        channel_list = chain['packet_filter']['list']
        for port, channel in channel_list:
            counterparty_chain_id, counterparty_port, counterparty_channel = get_counterparty_chain(ibc, port, channel)
            try:
                counterparty_chain_definition = registry.get_chain(counterparty_chain_id)
            except StopIteration:
                print("chain_id {} not found in config.".format(counterparty_chain_id))
                continue

            wallet = get_wallet_from_keyring(chain_id, chain['key_name'])
            try:
                wallet_counterparty = get_wallet_from_keyring(counterparty_chain_id,
                                                              next(item for item in config['chains'] if
                                                                   item["id"] == counterparty_chain_id)['key_name'])
            except StopIteration:
                print("chain_id {} not found in config.".format(counterparty_chain_id))
                continue

            cc = ChainChain(chain_name, counterparty_chain_definition['name'])
            cc.populate_chain_1(chain_id, channel, wallet)
            cc.populate_chain_2(counterparty_chain_id, counterparty_channel, wallet_counterparty)
            couple = cc.chain_couple()
            print(f"appending {couple}")
            ccs.append(couple)
    write_ccs(team_name=args.team_name, team_logo=args.team_logo, team_website=args.team_website,
              team_github=args.team_github, team_twitter=args.team_twitter, team_discord=args.team_discord,
              team_desc=args.team_description, ccs=ccs)
