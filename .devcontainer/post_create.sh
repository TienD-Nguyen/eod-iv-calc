#!/bin/bash
cp .devcontainer/auth.json "$HOME/.pi/agent/auth.json"
[ -f ".devcontainer/pi-footer.json" ] && cp ".devcontainer/pi-footer.json" "$HOME/.pi/agent/extensions/pi-footer.json"

# ---Install Pi extension---
pi install npm:pi-web-access
pi install npm:@juicesharp/rpiv-ask-user-question
pi install npm:@dietrichgebert/ponytail
pi install npm:pi-footer

echo "Pi Code Version: $(pi --version)$"
echo "UV Version: $(uv --version)"
echo "Git Version: $(git --version)"
echo "Python Version: $(python --version)"

echo "post-create setup complete"