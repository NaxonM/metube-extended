#!/bin/bash
#
# This script deploys or uninstalls the MeTubeEX system.
# It's designed to be run via curl:
# curl -sSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install.sh | bash
#
set -e

# --- Static Configuration ---
# These variables define the installation environment and default settings.
PROJECT_DIR_NAME="metube-extended"
PROJECT_DIR="$HOME/$PROJECT_DIR_NAME"
PERSISTENT_DATA_DIR="$HOME/.${PROJECT_DIR_NAME}-data"
REPO_URL="https://github.com/NaxonM/metube-extended.git"
ENV_FILE=".env"

detect_branch_from_invocation() {
    local url="${BASH_SOURCE[0]}"

    if [ "$url" = "install.sh" ] || [ "$url" = "$0" ]; then
        if [ -n "$SOURCE_BRANCH" ]; then
            echo "$SOURCE_BRANCH"
            return
        fi
        echo ""
        return
    fi

    if [[ "$url" =~ raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/install\.sh$ ]]; then
        echo "${BASH_REMATCH[3]}"
        return
    fi

    if [[ "$url" =~ ^https://.+/([^/]+)/install\.sh$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    if [ -n "$SOURCE_BRANCH" ]; then
        echo "$SOURCE_BRANCH"
        return
    fi

    echo ""
}

# --- Colors for beautiful output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'

# --- Helper Functions ---
log() {
    echo -e "${C_BLUE}==>${C_RESET} ${1}"
}
log_success() {
    echo -e "${C_GREEN}✓ SUCCESS:${C_RESET} ${1}"
}
log_error() {
    echo -e "${C_RED}✗ ERROR:${C_RESET} ${1}" >&2
    exit 1
}

get_public_ip() {
    # Attempt to fetch the public IPv4 address from a list of reliable services.
    local IP_SERVICES=("https://ifconfig.me" "https://api.ipify.org" "https://icanhazip.com")
    local IP_ADDR=""

    log "Attempting to automatically determine public IPv4 address..."
    for service in "${IP_SERVICES[@]}"; do
        IP_ADDR=$(curl -4 -s --fail --max-time 5 "$service")
        if [ -n "$IP_ADDR" ]; then
            echo "$IP_ADDR"
            return
        fi
    done

    # If all services fail, prompt the user.
    log "Could not automatically determine public IPv4 address."
    while true; do
        read -p "Please enter your public IPv4 address manually: " MANUAL_IP
        # Basic validation for an IP address format.
        if [[ $MANUAL_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "$MANUAL_IP"
            return
        else
            echo "Invalid IP address format. Please try again."
        fi
    done
}

# --- Core Logic Functions ---
show_usage() {
    echo "Usage: $0 [command | <branch-name>]"
    echo
    echo "Commands:"
    echo "  (no command)     Deploys the 'master' branch or updates the existing installation."
    echo "  <branch-name>    Deploys a specific branch or updates the existing installation to it."
    echo "  uninstall        Completely removes the system, its data, and configuration."
    echo
    echo "This script is idempotent. Running it again on an existing installation will"
    echo "automatically pull the latest changes and redeploy the application."
    exit 1
}

check_dependencies() {
    log "Checking for dependencies..."
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install it to continue."
    fi
    if ! docker info &> /dev/null; then
        log_error "The Docker daemon is not running. Please start Docker and try again."
    fi
    if ! command -v git &> /dev/null; then
        log_error "Git is not installed. Please install it to continue."
    fi
    log_success "All dependencies are satisfied."
}

# Handles the creation of the .env file on first-time setup.
handle_config() {
    if [ -f "$ENV_FILE" ]; then
        log "Configuration file found. Skipping configuration."
        return
    fi

    # Declare variables to hold the config values.
    local deployment_type="ip" # Default to ip
    local config_domain
    local config_email=""
    local config_cf_token=""
    local config_admin_user
    local config_admin_pass
    local config_http_port="8080"
    local config_https_port="8443"

    log "--- Interactive First-Time Setup ---"
    read -p "Do you want to use a custom domain with Cloudflare SSL? [y/N] " -n 1 -r; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        deployment_type="domain"
        read -p "Enter the domain name for your dashboard (e.g., metube.example.com): " config_domain
        read -p "Enter your email address for SSL certificate notifications: " config_email
        read -p "Enter the HTTP port to use [${config_http_port}]: " http_port_input
        config_http_port=${http_port_input:-$config_http_port}
        read -p "Enter the HTTPS port to use [${config_https_port}]: " https_port_input
        config_https_port=${https_port_input:-$config_https_port}
        log "Please provide your Cloudflare API Token (DNS Edit permission) for automatic SSL."
        read -s -p "Enter Cloudflare API Token: " config_cf_token; echo
        if [ -z "$config_cf_token" ]; then
            log_error "Cloudflare API token cannot be empty for domain-based deployment."
        fi
    else
        log "Proceeding with IP-based setup."
        log "Detecting public IP address..."
        config_domain=$(get_public_ip)
        log_success "Detected public IP: $config_domain"
    fi

    read -p "Enter the dashboard admin username: " config_admin_user
    while true; do
        read -s -p "Enter the dashboard admin password: " config_admin_pass; echo
        read -s -p "Confirm password: " ADMIN_PASSWORD_CONFIRM; echo
        [ "$config_admin_pass" = "$ADMIN_PASSWORD_CONFIRM" ] && break
        echo "Passwords do not match. Please try again."
    done

    log "Generating configuration file..."
    SECRET_KEY=$(openssl rand -hex 32)

    # Write the main .env file, excluding the Cloudflare token.
    cat <<EOF > "$ENV_FILE"
# --- General Configuration ---
DEPLOYMENT_TYPE="$deployment_type"
DOMAIN="$config_domain"
SERVER_NAME="$config_domain"
LETSENCRYPT_EMAIL="$config_email"
COMPOSE_PROJECT_NAME="$PROJECT_DIR_NAME"
HTTP_PORT="${config_http_port}"
HTTPS_PORT="${config_https_port}"

# --- Secret values (DO NOT COMMIT) ---
ADMIN_USERNAME="$config_admin_user"
ADMIN_PASSWORD="$config_admin_pass"
SECRET_KEY="$SECRET_KEY"
EOF
    log_success "Configuration saved to $ENV_FILE."

    # If using a domain, write the Cloudflare token to a separate, secure file.
    if [ "$deployment_type" = "domain" ]; then
        log "Writing Cloudflare token to a secure file..."
        echo "$config_cf_token" > ".cf_token"
        chmod 600 ".cf_token"
        log_success "Cloudflare token saved to .cf_token with restricted permissions."

        cat <<EOF >> "$ENV_FILE"
CLOUDFLARE_TOKEN_PATH="$(pwd)/.cf_token"
EOF
    fi
}

# Downloads the latest source code from the repository.
fetch_source_code() {
    log "Fetching latest source code from $REPO_URL on branch $REPO_BRANCH..."
    # Clone the specified branch of the repo into the current directory.
    # The --depth 1 flag performs a shallow clone, which is faster.
    if git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" .; then
        log_success "Source code cloned successfully."
    else
        log_error "Failed to clone repository. Please check the URL, branch name, and your connection."
    fi
}

install_system() {
    log "--- Starting MeTubeEX Deployment/Update ---"

    check_dependencies

    # Logic to handle new install vs. update
    if [ -d "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR/.git" ]; then
        log "Existing installation found. Proceeding with update..."
        cd "$PROJECT_DIR"

        log "[1/3] Updating application source to branch '$REPO_BRANCH'..."
        # Stash any local changes to avoid conflicts. These changes will be discarded.
        git stash > /dev/null 2>&1

        log "Fetching latest state for branch '$REPO_BRANCH'..."
        # Fetch the specific branch. This is crucial for shallow clones which do not track all branches.
        if ! git fetch origin "$REPO_BRANCH"; then
            git stash pop > /dev/null 2>&1 || true # Attempt to restore stashed changes on failure
            log_error "Failed to fetch branch '$REPO_BRANCH' from remote. Check your connection and branch name."
        fi

        log "Resetting local repository to match 'origin/$REPO_BRANCH'..."
        # This is a robust way to update. It checks out the branch, creating/updating it,
        # and resets it to the state of the fetched remote branch.
        if ! git checkout -B "$REPO_BRANCH" "FETCH_HEAD"; then
             git stash pop > /dev/null 2>&1 || true # Attempt to restore stashed changes on failure
            log_error "Failed to switch to and reset branch '$REPO_BRANCH'."
        fi

        # Discard the stash as we have hard-reset the branch to a clean state.
        git stash drop > /dev/null 2>&1 || true
        log_success "Source code updated successfully."

    elif [ ! -d "$PROJECT_DIR" ]; then
        log "No existing installation found. Proceeding with new deployment..."
        mkdir -p "$PROJECT_DIR"
        cd "$PROJECT_DIR"
        log "[1/3] Fetching application source from branch '$REPO_BRANCH'..."
        fetch_source_code
    else
        # Directory exists but is not a git repo, which is an error state.
        log_error "Project directory '$PROJECT_DIR' exists but is not a valid git repository. Please remove it and run the script again."
    fi

    log "[2/3] Initializing configuration..."
    handle_config

    # Source the .env file to get the variables we just saved.
    set -a
    source .env
    set +a

    log "Ensuring persistent data directory exists at $PERSISTENT_DATA_DIR..."
    mkdir -p "$PERSISTENT_DATA_DIR"
    export APP_DATA_PATH="$PERSISTENT_DATA_DIR"
    log_success "Application data will be stored in $APP_DATA_PATH"

    log "[3/3] Finalizing setup..."
    # Build the compose command based on the deployment type
    local compose_files="-f docker-compose.yml"
    if [ "$DEPLOYMENT_TYPE" = "domain" ]; then
        compose_files="$compose_files -f docker-compose.domain.yml"
        # Create persistent dir for acme.json only if using domain
        mkdir -p "$PERSISTENT_DATA_DIR"
        if [ ! -f "$PERSISTENT_DATA_DIR/acme.json" ]; then
            touch "$PERSISTENT_DATA_DIR/acme.json"
            chmod 600 "$PERSISTENT_DATA_DIR/acme.json"
        fi
        # Prepend env var for compose command
        export ACME_JSON_PATH="$PERSISTENT_DATA_DIR/acme.json"
        export CLOUDFLARE_TOKEN_PATH="$(pwd)/.cf_token"
        log "Enabling domain setup."
    else
        compose_files="$compose_files -f docker-compose.ip.yml"
        log "Enabling IP-based setup."
    fi

    docker compose $compose_files up -d --build --remove-orphans

    echo
    log_success "--- Deployment Complete ---"
    echo
    echo -e "Your MeTubeEX deployment should now be running!"

    if [ "$DEPLOYMENT_TYPE" = "domain" ]; then
        echo -e "Please allow a minute for the SSL certificate to be generated."
        echo -e "  ${C_YELLOW}Access your dashboard at: https://${DOMAIN}:${HTTPS_PORT}${C_RESET}"
    else
        echo -e "  ${C_YELLOW}Access your dashboard at: http://${DOMAIN}:8080${C_RESET}"
    fi
    echo
    echo -e "To view live logs, run: ${C_GREEN}cd ${PROJECT_DIR} && docker compose -p ${COMPOSE_PROJECT_NAME} logs -f${C_RESET}"
    echo -e "To stop the system, run: ${C_GREEN}cd ${PROJECT_DIR} && docker compose -p ${COMPOSE_PROJECT_NAME} down${C_RESET}"
}

uninstall_system() {
    log "--- Uninstalling MeTubeEX ---"

    local project_exists=false
    local data_exists=false
    local docker_available=false

    [ -d "$PROJECT_DIR" ] && project_exists=true
    [ -d "$PERSISTENT_DATA_DIR" ] && data_exists=true
    if command -v docker >/dev/null 2>&1; then
        docker_available=true
    fi

    if [ "$project_exists" = false ] && [ "$data_exists" = false ]; then
        log_success "No installation artifacts detected. Nothing to uninstall."
        exit 0
    fi

    echo -e "${C_YELLOW}This will permanently remove all containers, data, logs, and configuration for '$PROJECT_DIR_NAME'.${C_RESET}"
    read -p "Are you absolutely sure you want to continue? [y/N] " -n 1 -r; echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstall cancelled."
        exit 1
    fi

    if [ "$project_exists" = true ]; then
        cd "$PROJECT_DIR"
        if [ ! -f "docker-compose.yml" ]; then
            log_error "Could not find 'docker-compose.yml'. The directory may be corrupted. Manual removal is required."
        fi

        if [ "$docker_available" = true ]; then
            log "Shutting down containers and removing all associated data (volumes, images)..."
            docker compose down --volumes --rmi all
        else
            log "Docker CLI not found. Skipping container shutdown."
        fi

        cd ..
        log "Deleting project directory..."
        rm -rf "$PROJECT_DIR"
    else
        log "Project directory '$PROJECT_DIR' not found. Skipping source removal."
    fi

    if [ "$docker_available" = true ]; then
        log "Removing custom Docker image..."
        docker rmi "metube-extended-metube" >/dev/null 2>&1 || true

        log "Pruning unused Docker networks..."
        docker network prune -f >/dev/null 2>&1 || true
    else
        log "Docker CLI not found. Skipping Docker image and network cleanup."
    fi

    echo
    if [ "$data_exists" = true ]; then
        read -p "Do you also want to remove the persistent data directory? (Contains database, logs, and all downloaded files) [y/N] " -n 1 -r; echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log "Deleting persistent data directory at $PERSISTENT_DATA_DIR..."
            rm -rf "$PERSISTENT_DATA_DIR"
            log_success "Persistent data directory removed."
        else
            log "Skipping deletion of persistent data directory. Your data is safe at $PERSISTENT_DATA_DIR"
        fi
    else
        log "Persistent data directory not found; nothing to remove."
    fi

    log_success "Uninstallation complete. 👋"
}

# --- Main Script Router ---
detected_branch="$(detect_branch_from_invocation)"
if [ -n "$detected_branch" ]; then
    REPO_BRANCH="$detected_branch"
else
    REPO_BRANCH="main"
fi

case "$1" in
    uninstall)
        uninstall_system
        ;;
    install|"")
        # Use detected branch (or default 'main') for 'install' or no argument
        install_system
        ;;
    *)
        # Any other argument is treated as a branch name.
        REPO_BRANCH="$1"
        install_system
        ;;
esac