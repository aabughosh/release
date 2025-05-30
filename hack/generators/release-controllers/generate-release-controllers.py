#!/usr/bin/env python3

# Ignore dynamic imports
# pylint: disable=E0401, C0413

# Ignore large context objects
# pylint: disable=R0902, R0903

# All non-static methods in contexts
# pylint: disable=R0201

import argparse
# Allow TOOD
# pylint: disable=W0511
import json
import logging
import os
import pathlib
import sys

from config import Context, Config

# Change python path so we can import genlib
sys.path.append(str(pathlib.Path(__file__).absolute().parent.parent.joinpath('lib')))
import genlib

sys.path.append(str(pathlib.Path(__file__).absolute().parents[0]))
import content

logging.basicConfig(level=logging.INFO, format='[%(asctime)s:%(levelname)-7s] %(message)s')
logger = logging.getLogger()


def generate_app_ci_content(config, git_clone_dir):
    namespaces = []
    for private in (False, True):
        for arch in config.arches:
            context = Context(config, arch, private)
            namespaces.append(context.is_namespace)

            with genlib.GenDoc(config.paths.path_rc_deployments.joinpath(f'admin_deploy-{context.is_namespace}-controller.yaml'), context) as gendoc:
                content.add_imagestream_namespace_rbac(gendoc)
                content.add_release_payload_modifier_rbac(gendoc)

            with genlib.GenDoc(config.paths.path_rc_deployments.joinpath(f'deploy-{context.is_namespace}-controller.yaml'), context) as gendoc:
                content.add_osd_rc_deployments(gendoc)
                content.add_osd_files_cache_service_account_resources(gendoc)
                content.add_osd_files_cache_resources(gendoc)

    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('serviceaccount.yaml'), context=config) as gendoc:
        content.add_osd_rc_service_account_resources(gendoc)
        content.add_release_payload_modifier_service_account(gendoc)

    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('admin_deploy-ocp-publish-art.yaml'), context=config) as gendoc:
        content.add_art_publish(gendoc)

    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('admin_ocp-priv-puller.yaml'), context=config) as gendoc:
        content.add_ocp_priv_puller_token(gendoc)

    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('ibm_managed_control_plane_testing.yaml'), context=config) as gendoc:
        content.add_ibm_managed_control_plane_testing(gendoc)

    for path in config.paths.path_rc_rpms:
        with genlib.GenDoc(path.joinpath('rpms-ocp-3.11.yaml'), context=config) as gendoc:
            content.add_rpm_mirror_service(gendoc, git_clone_dir, '3.11')

    for path in config.paths.path_rc_rpms:
        for major_minor in config.releases:
            with genlib.GenDoc(path.joinpath(f'rpms-ocp-{major_minor}.yaml'), context=config) as gendoc:
                content.add_rpm_mirror_service(gendoc, git_clone_dir, major_minor)

    # If there is an annotation defined for the public release controller, use it as a template
    # for the private annotations.
    for annotation_path in config.paths.path_rc_annotations.glob('release-ocp-*.json'):
        if annotation_path.name.endswith('ci.json'):  # There are no CI annotations for the private controllers
            continue
        if '-stable' in annotation_path.name:  # There are no stable streams in private release controllers
            continue
        if '-dev-preview' in annotation_path.name:  # There are no dev-preview streams in private release controllers
            continue
        annotation_filename = os.path.basename(annotation_path)
        with open(annotation_path, mode='r', encoding='utf-8') as f:
            pub_annotation = json.load(f)
        print(str(annotation_path))
        priv_annotation = make_priv_annotation(pub_annotation)

        with config.paths.path_priv_rc_annotations.joinpath(annotation_filename).open(mode='w+', encoding='utf-8') as f:
            json.dump(priv_annotation, f, sort_keys=True, indent=4)

    # Generate the release-controller one-offs...
    context = Context(config, "x86_64", False)

    # Origin release-controller
    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('admin_deploy-origin-controller.yaml'), context) as gendoc:
        content.generate_origin_admin_resources(gendoc)

    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('deploy-origin-controller.yaml'), context) as gendoc:
        content.generate_origin_resources(gendoc)

    # Signer
    with genlib.GenDoc(config.paths.path_rc_deployments.joinpath('deploy-ci-signer.yaml'), context) as gendoc:
        content.generate_signer_resources(gendoc)

    # Release Admins RBAC
    content.generate_release_admin_rbac(config)

    # Release-controller Development RBAC
    content.generate_development_rbac(config)

    # TRT RBAC
    content.generate_trt_rbac(config)

    # Release Payload Controller
    content.add_release_payload_controller_resources(config, context)

    # Release Reimport Controller
    content.add_release_reimport_controller_resources(config, context, namespaces)

    # Release Mirror Cleanup Controller
    content.add_release_mirror_cleanup_controller_resources(config, context, namespaces)

def make_priv_annotation(pub_annotation):
    priv_annotation = dict(pub_annotation)
    priv_annotation['name'] += '-priv'
    # The "mirrorPrefix" is technically optional:
    if 'mirrorPrefix' in pub_annotation:
        priv_annotation['mirrorPrefix'] += '-priv'
    # The "multi" release-controller purposefully does not use the "to" annotation:
    if 'to' in pub_annotation:
        priv_annotation['to'] += '-priv'
    # use specific private alternate repo for private streams
    if 'alternateImageRepository' in pub_annotation:
        priv_annotation['alternateImageRepository'] += '-priv'
    priv_annotation.pop('check', None)  # Don't worry about the state of other releases
    priv_annotation.pop('publish', None)  # Don't publish these images anywhere
    priv_annotation.pop('periodic', None)  # Don't configure periodics
    priv_annotation['message'] = "<!-- GENERATED FROM PUBLIC ANNOTATION CONFIG - DO NOT EDIT. -->" + priv_annotation['message']
    for _, test_config in priv_annotation['verify'].items():
        test_config['prowJob']['name'] += '-priv'
        # TODO: Private jobs are disabled until the -priv variants can be generated by prowgen
        test_config['disabled'] = True
    return priv_annotation

def run(git_clone_dir, bump=False):
    config = Config(git_clone_dir)

    # Generate version specific files (if necessary)
    content.bump_versioned_resources(config, bump)

    # New (app.ci) configuration and deployment
    generate_app_ci_content(config, git_clone_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Release Controller Configuration Generator')
    parser.add_argument('-b', '--bump', help='Create configuration for the next release (4.x+1).', action='store_true')
    parser.add_argument('-v', '--verbose', help='Enable verbose output.', action='store_true')
    parser.add_argument('clone_dir', help='Specify path to openshift/release clone directory.')

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    run(args.clone_dir, args.bump)
