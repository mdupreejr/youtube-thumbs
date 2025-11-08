#!/bin/bash

# This script sets up git configuration for Claude Code action
# Source this in Claude's environment to enable git operations

set -e

echo "Setting up git configuration for Claude..."

# Configure git user
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"

# Configure git credential helper
git config --global credential.helper store

# Set up credentials for GitHub
if [ -n "$GITHUB_TOKEN" ]; then
    echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
    echo "✅ GitHub credentials configured"
else
    echo "⚠️ GITHUB_TOKEN not found in environment"
fi

# Allow operations in any directory
git config --global --add safe.directory '*'

# Verify configuration
echo "Git user: $(git config user.name) <$(git config user.email)>"
echo "✅ Git configuration complete"
