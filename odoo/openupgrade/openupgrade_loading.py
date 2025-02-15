# coding: utf-8
# Copyright 2011-2015 Therp BV <https://therp.nl>
# Copyright 2016 Opener B.V. <https://opener.am>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from odoo import release
from openupgradelib.openupgrade_tools import table_exists
from odoo.tools import config, safe_eval
from odoo.modules.module import get_module_path
from odoo.tools import pycompat


# A collection of functions used in
# openerp/modules/loading.py

logger = logging.getLogger('OpenUpgrade')


def add_module_dependencies(cr, module_list):
    """
    Select (new) dependencies from the modules in the list
    so that we can inject them into the graph at upgrade
    time. Used in the modified OpenUpgrade Server,
    not to be called from migration scripts

    Also take the OpenUpgrade configuration directives 'forced_deps'
    and 'autoinstall' into account. From any additional modules
    that these directives can add, the dependencies are added as
    well (but these directives are not checked for the occurrence
    of any of the dependencies).
    """
    if not module_list:
        return module_list

    modules_in = list(module_list)
    forced_deps = safe_eval(
        config.get_misc(
            'openupgrade', 'forced_deps_' + release.version,
            config.get_misc('openupgrade', 'forced_deps', '{}')))

    autoinstall = safe_eval(
        config.get_misc(
            'openupgrade', 'autoinstall_' + release.version,
            config.get_misc('openupgrade', 'autoinstall', '{}')))

    for module in list(module_list):
        module_list += forced_deps.get(module, [])
        module_list += autoinstall.get(module, [])

    module_list = list(set(module_list))

    dependencies = module_list
    while dependencies:
        cr.execute("""
            SELECT DISTINCT dep.name
            FROM
                ir_module_module,
                ir_module_module_dependency dep
            WHERE
                module_id = ir_module_module.id
                AND ir_module_module.name in %s
                AND dep.name not in %s
            """, (tuple(dependencies), tuple(module_list),))

        dependencies = [x[0] for x in cr.fetchall()]
        module_list += dependencies

    # Select auto_install modules of which all dependencies
    # are fulfilled based on the modules we know are to be
    # installed
    cr.execute("""
        SELECT name from ir_module_module WHERE state IN %s
        """, (('installed', 'to install', 'to upgrade'),))
    modules = list(set(module_list + [row[0] for row in cr.fetchall()]))
    cr.execute("""
        SELECT name from ir_module_module m
        WHERE auto_install IS TRUE
            AND state = 'uninstalled'
            AND NOT EXISTS(
                SELECT id FROM ir_module_module_dependency d
                WHERE d.module_id = m.id
                AND name NOT IN %s)
         """, (tuple(modules),))
    auto_modules = [
        row[0] for row in cr.fetchall()
        if get_module_path(row[0])
    ]
    if auto_modules:
        logger.info(
            "Selecting autoinstallable modules %s", ','.join(auto_modules))
        module_list += auto_modules

    # Set proper state for new dependencies so that any init scripts are run
    cr.execute("""
        UPDATE ir_module_module SET state = 'to install'
        WHERE name IN %s AND name NOT IN %s AND state = 'uninstalled'
        """, (tuple(module_list), tuple(modules_in)))
    return module_list


def log_model(model, local_registry):
    """
    OpenUpgrade: Store the characteristics of the BaseModel and its fields
    in the local registry, so that we can compare changes with the
    main registry
    """

    if not model._name:
        return

    typemap = {'monetary': 'float'}

    # Deferred import to prevent import loop
    from odoo import models

    # persistent models only
    if isinstance(model, models.TransientModel):
        return

    def isfunction(model, k):
        if (model._fields[k].compute and
                not model._fields[k].related and
                not model._fields[k].company_dependent):
            return 'function'
        return ''

    def isproperty(model, k):
        if model._fields[k].company_dependent:
            return 'property'
        return ''

    def isrelated(model, k):
        if model._fields[k].related:
            return 'related'
        return ''

    model_registry = local_registry.setdefault(
        model._name, {})
    if model._inherits:
        model_registry['_inherits'] = {
            '_inherits': pycompat.text_type(model._inherits)}
    model_registry['_order'] = {'_order': str(model._order)}
    for k, v in model._fields.items():
        properties = {
            'type': typemap.get(v.type, v.type),
            'isfunction': isfunction(model, k),
            'isproperty': isproperty(model, k),
            'isrelated': isrelated(model, k),
            'relation': v.comodel_name if v.type in (
                'many2many', 'many2one', 'one2many') else '',
            'table': v.relation if v.type == 'many2many' else '',
            'required': v.required and 'required' or '',
            'stored': v.store and 'stored' or '',
            'selection_keys': '',
            'req_default': '',
            'hasdefault': model._fields[k].default and 'hasdefault' or '',
            'inherits': '',
            }
        if hasattr(v, 'oldname'):
            properties['oldname'] = v.oldname
        if v.type == 'selection':
            if isinstance(v.selection, (tuple, list)):
                properties['selection_keys'] = pycompat.text_type(
                    sorted([x[0] for x in v.selection]))
            else:
                properties['selection_keys'] = 'function'
        elif v.type == 'binary':
            properties['attachment'] = str(getattr(v, "attachment", False))
        default = model._fields[k].default
        if v.required and default:
            if callable(default) or isinstance(
                    default, pycompat.string_types) and \
                    getattr(model._fields[k], default, False) and \
                    callable(getattr(model._fields[k], default)):
                # todo: in OpenERP 5 (and in 6 as well),
                # literals are wrapped in a lambda function
                properties['req_default'] = 'function'
            else:
                properties['req_default'] = pycompat.text_type(default)
        for key, value in properties.items():
            if value:
                model_registry.setdefault(k, {})[key] = value


def get_record_id(cr, module, model, field, mode):
    """
    OpenUpgrade: get or create the id from the record table matching
    the key parameter values
    """
    cr.execute(
        "SELECT id FROM openupgrade_record "
        "WHERE module = %s AND model = %s AND "
        "field = %s AND mode = %s AND type = %s",
        (module, model, field, mode, 'field')
        )
    record = cr.fetchone()
    if record:
        return record[0]
    cr.execute(
        "INSERT INTO openupgrade_record "
        "(module, model, field, mode, type) "
        "VALUES (%s, %s, %s, %s, %s)",
        (module, model, field, mode, 'field')
        )
    cr.execute(
        "SELECT id FROM openupgrade_record "
        "WHERE module = %s AND model = %s AND "
        "field = %s AND mode = %s AND type = %s",
        (module, model, field, mode, 'field')
        )
    return cr.fetchone()[0]


def compare_registries(cr, module, registry, local_registry):
    """
    OpenUpgrade: Compare the local registry with the global registry,
    log any differences and merge the local registry with
    the global one.
    """
    if not table_exists(cr, 'openupgrade_record'):
        return
    for model, flds in local_registry.items():
        registry.setdefault(model, {})
        for field, attributes in flds.items():
            old_field = registry[model].setdefault(field, {})
            mode = old_field and 'modify' or 'create'
            record_id = False
            for key, value in attributes.items():
                if key not in old_field or old_field[key] != value:
                    if not record_id:
                        record_id = get_record_id(
                            cr, module, model, field, mode)
                    cr.execute(
                        "SELECT id FROM openupgrade_attribute "
                        "WHERE name = %s AND value = %s AND "
                        "record_id = %s",
                        (key, value, record_id)
                        )
                    if not cr.fetchone():
                        cr.execute(
                            "INSERT INTO openupgrade_attribute "
                            "(name, value, record_id) VALUES (%s, %s, %s)",
                            (key, value, record_id)
                            )
                    old_field[key] = value
