#!/bin/bash

# Script to detect host resources and set Docker limits to half of available resources

# Detect number of CPU cores
HOST_CPUS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)
HOST_CPUS=${HOST_CPUS:-2}

# Detect total memory in GB
if command -v free >/dev/null 2>&1; then
    HOST_MEMORY_GB=$(free -g | awk 'NR==2{printf "%.0f", $2}')
elif command -v sysctl >/dev/null 2>&1; then
    HOST_MEMORY_KB=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    HOST_MEMORY_GB=$((HOST_MEMORY_KB / 1024 / 1024 / 1024))
else
    HOST_MEMORY_GB=4  # Default fallback
fi
HOST_MEMORY_GB=${HOST_MEMORY_GB:-4}

# Calculate half of resources (minimum 1 CPU, 1GB RAM)
CPU_LIMIT=$(awk "BEGIN {print ($HOST_CPUS / 2 > 1) ? $HOST_CPUS / 2 : 1}")
MEMORY_LIMIT_GB=$(awk "BEGIN {print ($HOST_MEMORY_GB / 2 > 1) ? $HOST_MEMORY_GB / 2 : 1}")

# Set environment variables for docker-compose
export CPU_LIMIT="${CPU_LIMIT}"
export MEMORY_LIMIT="${MEMORY_LIMIT_GB}G"
export CPU_RESERVATION=$(awk "BEGIN {print ($CPU_LIMIT / 2 > 0.5) ? $CPU_LIMIT / 2 : 0.5}")
export MEMORY_RESERVATION=$(awk "BEGIN {print ($MEMORY_LIMIT_GB / 2 > 0.5) ? $MEMORY_LIMIT_GB / 2 : 0.5}G")

# Also set app-specific limits
export CPU_LIMIT_PERCENT=80
export MEMORY_LIMIT_MB=$((MEMORY_LIMIT_GB * 1024))
export DISK_READ_IOPS=1000
export DISK_WRITE_IOPS=1000
export NETWORK_BANDWIDTH_MB=62.5  # 500 Mb/s
export MAX_CONCURRENT_DOWNLOADS=5

# Output for debugging
echo "Host specs: $HOST_CPUS CPUs, ${HOST_MEMORY_GB}GB RAM"
echo "Docker limits: $CPU_LIMIT CPUs, ${MEMORY_LIMIT_GB}GB RAM"
echo "App limits: CPU ${CPU_LIMIT_PERCENT}%, Memory ${MEMORY_LIMIT_MB}MB, Network 500 Mb/s, Downloads $MAX_CONCURRENT_DOWNLOADS"

# Generate .env file for docker-compose
cat > .env << EOF
CPU_LIMIT=${CPU_LIMIT}
MEMORY_LIMIT=${MEMORY_LIMIT}
CPU_RESERVATION=${CPU_RESERVATION}
MEMORY_RESERVATION=${MEMORY_RESERVATION}
CPU_LIMIT_PERCENT=${CPU_LIMIT_PERCENT}
MEMORY_LIMIT_MB=${MEMORY_LIMIT_MB}
DISK_READ_IOPS=${DISK_READ_IOPS}
DISK_WRITE_IOPS=${DISK_WRITE_IOPS}
NETWORK_BANDWIDTH_MB=${NETWORK_BANDWIDTH_MB}
MAX_CONCURRENT_DOWNLOADS=${MAX_CONCURRENT_DOWNLOADS}
EOF

echo ".env file generated with resource limits."