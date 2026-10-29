#!/usr/bin/env sh
# Copy the shared pdtracker package next to function_app.py so it deploys with the function.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$here/pdtracker"
cp -r "$here/../../pdtracker" "$here/pdtracker"
find "$here/pdtracker" -name __pycache__ -prune -exec rm -rf {} +
echo "Copied pdtracker into $here. Deploy with: func azure functionapp publish <app-name> --python"
