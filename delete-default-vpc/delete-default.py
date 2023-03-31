#!/usr/bin/env python3
"""
Script to delete default VPCs and their associated resources in AWS regions.

This script performs the following actions:
1. Retrieves a list of available AWS regions, or accepts a list of regions from the user.
2. Iterates through each region, identifying default VPCs and their associated resources.
3. Deletes the default VPCs, associated resources, and dependent resources (security groups, network interfaces, and route tables).

Usage:
    To run the script, simply execute it from the command line:
    $ python delete_default_vpcs.py

    To specify a list of regions, use the --regions flag followed by a space-separated list of region names:
    $ python delete_default_vpcs.py --regions us-east-1 us-west-1

    To skip confirmation before deleting resources, use the --no-confirm flag:
    $ python delete_default_vpcs.py --no-confirm

    You can combine the --regions and --no-confirm flags:
    $ python delete_default_vpcs.py --regions us-east-1 us-west-1 --no-confirm
"""
import os
import boto3
import logging
import argparse

INDENT = '    '

# Initialize the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a console handler to log messages to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter for the log messages
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Add the console handler to the logger
logger.addHandler(console_handler)

ec2 = boto3.client('ec2')

def confirm_delete(resources, no_confirm):
    if no_confirm:
        print("Warning: Skipping confirmation due to the --no-confirm flag.")
        return True

    print("The following resources will be deleted:")
    for resource in resources:
        print(resource)
    while True:
        confirmation = input("Delete these resources? [y/n]: ")
        if confirmation.lower() == 'y':
            return True
        elif confirmation.lower() == 'n':
            return False
        else:
            print("Invalid input. Please enter 'y' or 'n'.")

def delete_dependent_resources(vpc):
    # Delete Internet Gateways
    try:
        igws = ec2.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc]}])['InternetGateways']
        for igw in igws:
            ec2.detach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc)
            ec2.delete_internet_gateway(InternetGatewayId=igw['InternetGatewayId'])
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting internet gateways: {e}")
        raise

    # Delete Subnets
    try:
        subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc]}])['Subnets']
        for subnet in subnets:
            ec2.delete_subnet(SubnetId=subnet['SubnetId'])
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting subnets: {e}")
        raise

    # Disassociate and delete Route Tables
    try:
        route_tables = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc]}])['RouteTables']
        for rt in route_tables:
            for association in rt['Associations']:
                if not association['Main']:
                    ec2.disassociate_route_table(AssociationId=association['RouteTableAssociationId'])
            if not any(association['Main'] for association in rt['Associations']):
                ec2.delete_route_table(RouteTableId=rt['RouteTableId'])
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting route tables: {e}")
        raise

    # Delete network ACLs
    try:
        network_acls = ec2.describe_network_acls(Filters=[{'Name': 'vpc-id', 'Values': [vpc]}])['NetworkAcls']
        for acl in network_acls:
            if not acl['IsDefault']:
                ec2.delete_network_acl(NetworkAclId=acl['NetworkAclId'])
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting network ACLs: {e}")
        raise

    # Delete Security Groups
    try:
        security_groups = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc]}])['SecurityGroups']
        for sg in security_groups:
            if sg['GroupName'] != 'default':
                ec2.delete_security_group(GroupId=sg['GroupId'])
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting security groups: {e}")
        raise

    # Delete VPC
    try:
        ec2.delete_vpc(VpcId=vpc)
    except Exception as e:
        logger.error(f"{INDENT}An error occurred while deleting the VPC: {e}")
        raise

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete default VPCs in specified AWS regions.')
    parser.add_argument('--regions', metavar='R', nargs='+', help='a list of AWS regions')
    parser.add_argument('--no-confirm', action='store_true', help='skip confirmation before deleting resources')
    args = parser.parse_args()

    REGIONS = [region['RegionName'] for region in ec2.describe_regions()['Regions']]

    if args.regions:
        REGIONS = args.regions

    for region in REGIONS:
        os.environ['AWS_DEFAULT_REGION'] = region
        logger.info(f"* Region {region}")

        # get default vpc
        try:
            vpcs = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
            if not vpcs['Vpcs']:
                logger.info(f"{INDENT}No default vpc found")
                continue
        except Exception as e:
            logger.error(f"{INDENT}An error occurred while describing VPCs: {e}")
            continue
        vpc = vpcs['Vpcs'][0]['VpcId']
        logger.info(f"{INDENT}Found default vpc {vpc}")

        # get internet gateway
        try:
            igws = ec2.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc]}])
            igw = igws['InternetGateways'][0]['InternetGatewayId'] if igws['InternetGateways'] else None
        except Exception as e:
            logger.error(f"{INDENT}An error occurred while describing internet gateways: {e}")
            continue

        # get subnets
        try:
            subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc]}])['Subnets']
        except Exception as e:
            logger.error(f"{INDENT}An error occurred while describing subnets: {e}")
            continue

        resources = []
        if igw:
            resources.append(f"{INDENT}Internet gateway {igw}")
        for subnet in subnets:
            subnet_id = subnet['SubnetId']
            resources.append(f"{INDENT}Subnet {subnet_id}")
        resources.append(f"{INDENT}VPC {vpc}")

        if confirm_delete(resources, args.no_confirm):
            try:
                delete_dependent_resources(vpc)
                delete_resources(vpc, igw, subnets)
            except Exception as e:
                logger.error(f"{INDENT}An error occurred while deleting resources: {e}")
