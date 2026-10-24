import os
import tempfile

# Tests sans affichage et sans toucher à la configuration de l'utilisateur.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_tmp = tempfile.mkdtemp(prefix="linxdiagram-tests-")
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(_tmp, var.lower())
