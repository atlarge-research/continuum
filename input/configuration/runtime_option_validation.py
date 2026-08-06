"""Runtime option-validation helpers for provider and orchestrator modules."""

from application import application
from infrastructure import infrastructure
from input.configuration import benchmark_stage_contract, config_access, module_contract_validation
from input.configuration.runtime_option_contract import CORE_PROVIDER_CONFIG_KEYS
from resource_manager import resource_manager


def _scope_path(parser, config, scope):
    """Return the mutable domain config mapping for a module option scope."""
    domains = config.get("domains")
    if not isinstance(domains, dict):
        parser.error("Config: Missing option scope domains")

    if scope == "resource_manager":
        try:
            module = config_access.orchestrator_module(config)
        except ValueError as exc:
            parser.error(
                "Config: Missing option scope %s (%s)" % (_scope_label(scope, config), exc)
            )
        module_cfg = module.get("config")
        if not isinstance(module_cfg, dict):
            parser.error("Config: Missing option scope %s" % (_scope_label(scope, config)))
        return module_cfg

    if scope == "application":
        try:
            stage = config_access.benchmark_primary_stage(config)
        except ValueError as exc:
            parser.error(
                "Config: Missing option scope %s (%s)" % (_scope_label(scope, config), exc)
            )
        stage_cfg = stage.get("config")
        if not isinstance(stage_cfg, dict):
            parser.error("Config: Missing option scope %s" % (_scope_label(scope, config)))
        return stage_cfg

    if scope == "provider":
        provider = domains.get("provider")
        if not isinstance(provider, dict):
            parser.error("Config: Missing option scope %s" % (_scope_label(scope, config)))
        provider_cfg = provider.get("config")
        if not isinstance(provider_cfg, dict):
            parser.error("Config: Missing option scope %s" % (_scope_label(scope, config)))
        return provider_cfg
    parser.error("Config: Unknown option scope %s" % (_scope_label(scope, config)))


def _scope_label(scope, config=None):
    """Return a human-readable config path label used in parser errors."""
    if scope == "application":
        return "domains.benchmark.pipeline[*].config"
    if scope == "resource_manager":
        if config is not None:
            try:
                index = config_access.orchestrator_module_index(config)
                return "domains.software.modules[%s].config" % (index)
            except ValueError:
                pass
        return "domains.software.modules[orchestrator].config"
    if scope == "provider":
        return "domains.provider.config"
    return "domains.unknown.config"


def _coerce_option_value(parser, config, scope, option, intype, value):
    """Coerce a raw domain option value to the declared option type."""
    try:
        if intype == int:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if intype == float:
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if intype == bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "false"):
                    return lowered == "true"
            raise ValueError
        if intype == str:
            if not isinstance(value, str):
                raise ValueError
            return value
        if intype == list:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [part.strip() for part in value.split(",") if part.strip()]
            raise ValueError
    except ValueError:
        parser.error(
            "Config: Invalid type for option %s->%s, expected %s"
            % (_scope_label(scope, config), option, intype)
        )

    parser.error("Config: Invalid type %s" % (intype))


def _default_value(intype, default):
    """Return a typed default value from an option descriptor default."""
    if default is None or isinstance(default, bool):
        return default
    return intype(default)


def _validate_option(parser, config, scope, setting):
    """Validate a single module option descriptor against domain config."""
    option, intype, condition, mandatory, default = setting
    domain_cfg = _scope_path(parser, config, scope)
    domain_key = option

    if domain_key in domain_cfg and domain_cfg[domain_key] != "":
        value = _coerce_option_value(parser, config, scope, option, intype, domain_cfg[domain_key])
    elif mandatory:
        parser.error("Config: Missing option %s->%s" % (_scope_label(scope, config), option))
    else:
        value = _default_value(intype, default)

    if value == "" and mandatory:
        parser.error("Config: Missing option %s->%s" % (_scope_label(scope, config), option))

    if not condition(value):
        parser.error("Config: Invalid value for option %s->%s" % (_scope_label(scope, config), option))

    domain_cfg[domain_key] = value


def _validate_no_unknown_options(parser, config, scope, allowed_domain_keys):
    """Fail fast when a module config scope contains unknown option keys."""
    domain_cfg = _scope_path(parser, config, scope)
    unknown = sorted(key for key in domain_cfg if key not in allowed_domain_keys)
    if unknown:
        parser.error(
            "Config: Unknown option(s) in %s: %s"
            % (_scope_label(scope, config), ", ".join(unknown))
        )


def _constraint_type(stage_type, option, constraint_label):
    """Map canonical benchmark-stage contract labels onto runtime option types."""
    if option == "frequency" and stage_type == "text_translation":
        return float
    if constraint_label.startswith("integer"):
        return int
    if constraint_label.startswith("number"):
        return float
    raise ValueError(
        "Unsupported benchmark contract label %r for stage %r option %r"
        % (constraint_label, stage_type, option)
    )


def _application_contract_settings(config, declared_options):
    """Return canonical benchmark-stage option descriptors not declared by the app module."""
    try:
        stage_type = config_access.benchmark_primary_stage_type(config)
    except ValueError:
        return []
    rules = benchmark_stage_contract.BENCHMARK_STAGE_CONFIG_RULES.get(stage_type, {})
    settings = []
    for option, (constraint_label, validator) in rules.items():
        if option in declared_options:
            continue
        settings.append(
            (
                option,
                _constraint_type(stage_type, option, constraint_label),
                validator,
                True,
                None,
            )
        )
    return settings


def apply_module_options(parser, config):
    """Validate/default module options and return provider-specific config keys."""
    settings = []
    provider_config_keys = set()
    allowed_domain_keys = {
        "application": set(),
        "provider": set(),
        "resource_manager": set(),
    }

    if config["module"]["application"]:
        application_settings = application.add_options(config) or []
        settings.extend([("application", s) for s in application_settings])
        declared_application_options = {setting[0] for setting in application_settings}
        settings.extend(
            [
                ("application", setting)
                for setting in _application_contract_settings(
                    config,
                    declared_application_options,
                )
            ]
        )
    if config["module"]["provider"]:
        allowed_domain_keys["provider"] = set(CORE_PROVIDER_CONFIG_KEYS)
        setting = infrastructure.add_options(config)
        if setting:
            settings.extend([("provider", s) for s in setting])
    if config["module"]["resource_manager"]:
        setting = resource_manager.add_options(config)
        if setting:
            settings.extend([("resource_manager", s) for s in setting])

    for scope, setting in settings:
        option = setting[0]
        if scope not in allowed_domain_keys:
            parser.error("Config: Unknown option scope %s" % (_scope_label(scope, config)))
        allowed_domain_keys[scope].add(option)
        if scope == "provider":
            provider_config_keys.add(option)
        _validate_option(parser, config, scope, setting)

    if config["module"]["application"]:
        _validate_no_unknown_options(
            parser,
            config,
            "application",
            allowed_domain_keys["application"],
        )
    if config["module"]["resource_manager"]:
        _validate_no_unknown_options(
            parser,
            config,
            "resource_manager",
            allowed_domain_keys["resource_manager"],
        )
    if config["module"]["provider"]:
        _validate_no_unknown_options(
            parser,
            config,
            "provider",
            allowed_domain_keys["provider"],
        )

    return tuple(sorted(provider_config_keys))


def verify_addon_compatibility(parser, config):
    """Verify addon compatibility constraints."""
    modules = config_access.software_modules(config)
    endpoint_nodes = int(config["infrastructure"]["endpoint_nodes"])
    endpoint_resource_vm_ids = None
    if endpoint_nodes > 0 and config_access.has_addon(config, "endpoint_runtime"):
        try:
            normalized = config["normalized"]
            resources = normalized["infrastructure"]["resources"]
            endpoint_resource_vm_ids = set()
            for resource in resources:
                if not isinstance(resource, dict):
                    raise ValueError(
                        "normalized.infrastructure.resources must contain mappings"
                    )
                vm_id = resource.get("vm_id")
                tags = resource.get("tags")
                if (
                    isinstance(vm_id, int)
                    and not isinstance(vm_id, bool)
                    and isinstance(tags, dict)
                    and tags.get("tier") == "endpoint"
                ):
                    endpoint_resource_vm_ids.add(vm_id)
            if not endpoint_resource_vm_ids:
                raise ValueError(
                    "normalized.infrastructure.resources must include endpoint tier resources"
                )
        except ValueError as exc:
            parser.error("ERROR: %s" % (exc,))
        except (KeyError, TypeError) as exc:
            parser.error(
                "ERROR: Missing canonical normalized infrastructure resources: %s" % (exc,)
            )
    evaluation = module_contract_validation.evaluate_module_contracts(
        modules,
        set(config_access.run_targets(config)),
        require_endpoint_runtime=endpoint_nodes > 0,
        treat_missing_scope_as_global=True,
        endpoint_resource_vm_ids=endpoint_resource_vm_ids,
    )

    requires_error_overrides = {
        ("openfaas", "orchestrator.kubernetes"): "ERROR: OpenFaaS addon requires orchestrator Kubernetes",
        (
            "observability",
            "capability.observability_host",
        ): "ERROR: Observability addon requires orchestrator observability support",
    }
    for violation in evaluation["violations"]:
        kind = violation.get("kind")
        if kind == "endpoint_runtime_missing":
            parser.error(
                "ERROR: Endpoint nodes require a software addon with endpoint-runtime capability "
                "(currently addon name=endpoint_runtime)"
            )
            continue

        if kind == "endpoint_runtime_not_on_endpoint":
            module_id, module_type = module_contract_validation.module_identity(violation["module"])
            parser.error(
                "ERROR: Endpoint runtime module %s (type=%s) must be assigned to endpoint resources"
                % (module_id, module_type)
            )
            continue

        if kind == "exclusive":
            module_id, module_type = module_contract_validation.module_identity(violation["module"])
            left_module_id, _left_module_type = module_contract_validation.module_identity(
                violation["other_module"]
            )
            scope_identity = violation["scope_identity"]
            if scope_identity is None:
                parser.error(
                    "ERROR: Module %s (type=%s) conflicts: capability %s is exclusive and already "
                    "provided by module %s"
                    % (module_id, module_type, violation["capability"], left_module_id)
                )
            else:
                parser.error(
                    "ERROR: Module %s (type=%s) conflicts: capability %s is exclusive and already "
                    "provided by module %s in scope %s"
                    % (module_id, module_type, violation["capability"], left_module_id, scope_identity)
                )
            continue

        if kind == "requires":
            module_id, module_type = module_contract_validation.module_identity(violation["module"])
            requirement = violation["required_capability"]
            parser.error(
                requires_error_overrides.get(
                    (module_type, requirement),
                    "ERROR: Module %s (type=%s) requires capability %s"
                    % (module_id, module_type, requirement),
                )
            )
            continue

        if kind == "requires_scope":
            module_id, module_type = module_contract_validation.module_identity(violation["module"])
            requirement = violation["required_capability"]
            parser.error(
                "%s in an overlapping assignment scope"
                % (
                    requires_error_overrides.get(
                        (module_type, requirement),
                        "ERROR: Module %s (type=%s) requires capability %s"
                        % (module_id, module_type, requirement),
                    ),
                )
            )
            continue

        if kind == "conflict":
            module_id, module_type = module_contract_validation.module_identity(violation["module"])
            provider_module_id, _provider_type = module_contract_validation.module_identity(
                violation["provider_module"]
            )
            scope_identity = violation["scope_identity"]
            if scope_identity is None:
                parser.error(
                    "ERROR: Module %s (type=%s) conflicts with module %s via capability %s"
                    % (
                        module_id,
                        module_type,
                        provider_module_id,
                        violation["conflict_capability"],
                    )
                )
            else:
                parser.error(
                    "ERROR: Module %s (type=%s) conflicts with module %s via capability %s in scope %s"
                    % (
                        module_id,
                        module_type,
                        provider_module_id,
                        violation["conflict_capability"],
                        scope_identity,
                    )
                )
            continue

    if config_access.has_addon(config, "openfaas"):
        if config_access.orchestrator_bool_optional(config, "cache_worker", default=False):
            parser.error("ERROR: OpenFaaS app does not support application caching")


def verify_options(parser, config):
    """Verify the config against selected module requirements."""
    verify_addon_compatibility(parser, config)
    if config["module"]["application"]:
        application.verify_options(parser, config)
    if config["module"]["provider"]:
        infrastructure.verify_options(parser, config)
    if config["module"]["resource_manager"]:
        resource_manager.verify_options(parser, config)
