from tasks.post_login_modules.inventory_probe import InventoryProbeModule
from tasks.post_login_modules.inventory_ensure_open import InventoryEnsureOpenModule
from tasks.post_login_modules.inventory_grid_probe import InventoryGridProbeModule


MODULE_CLASSES = (
    InventoryProbeModule,
    InventoryEnsureOpenModule,
    InventoryGridProbeModule,
)


def enabled_post_login_modules(launcher):
    modules = []
    for module_class in MODULE_CLASSES:
        try:
            module = module_class(launcher)
            if module.enabled():
                modules.append(module)
        except Exception as error:
            print(f"Post-login module init failed: {module_class.__name__}: {error}")
    return modules


def has_enabled_post_login_modules(launcher):
    return bool(enabled_post_login_modules(launcher))


def run_enabled_post_login_modules(launcher, account_index, session):
    modules = enabled_post_login_modules(launcher)
    if not modules:
        return "NO_ENABLED_POST_LOGIN_MODULES"

    for module in modules:
        try:
            print(
                "Post-login module start - "
                f"module={module.name} - account={account_index + 1}"
            )
            result = module.run(account_index, session)
            if result == "SKIPPED":
                continue
            if result != "OK":
                print(
                    "Post-login module failed - "
                    f"module={module.name} - account={account_index + 1} - result={result}"
                )
                return result
            print(
                "Post-login module OK - "
                f"module={module.name} - account={account_index + 1}"
            )
        except Exception as error:
            print(
                "Post-login module exception - "
                f"module={getattr(module, 'name', type(module).__name__)} - "
                f"account={account_index + 1} - {error}"
            )
            return "POST_LOGIN_MODULE_EXCEPTION"

    return "OK"
