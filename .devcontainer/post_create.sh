#!/bin/bash
cp .devcontainer/auth.json "$HOME/.pi/agent/auth.json"

# ---Install Pi extension---
pi install npm:pi-web-access
pi install npm:@juicesharp/rpiv-ask-user-question
pi install npm:@dietrichgebert/ponytail

echo "Pi Code Version: $(pi --version)$"
echo "UV Version: $(uv --version)"
echo "Git Version: $(git --version)"
echo "Python Version: $(python --version)"

echo "post-create setup complete"