FROM registry.fedoraproject.org/fedora-minimal:latest

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

# -----Basic setup and installations-----
RUN microdnf update -y --refresh && \
    microdnf install git sudo tar curl wget ripgrep ca-certificates npm -y && \
    microdnf clean all

RUN groupadd --gid ${USER_UID} ${USERNAME} && \
    useradd --comment "VSCode User Account" --gid ${USER_GID} --uid ${USER_UID} -p ${USERNAME} -G wheel -s /bin/bash -m ${USERNAME}


# -----Install & Set ENV for UV-----
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# -----Setup & Install Pi Coding Agent-----
RUN mkdir -p /home/${USERNAME}/.pi/agent && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/.pi/agent

RUN node --version && \
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent@latest && \
    pi --version

USER $USERNAME
WORKDIR /workspaces