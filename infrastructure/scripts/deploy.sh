#!/bin/bash
# Deployment script that verifies all tests pass before deploying infrastructure
# Usage: ./scripts/deploy.sh [--skip-tests] [--skip-build] [--skip-bootstrap]

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
SKIP_TESTS=false
SKIP_BUILD=false
SKIP_BOOTSTRAP=false

for arg in "$@"; do
    case $arg in
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-bootstrap)
            SKIP_BOOTSTRAP=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $arg${NC}"
            echo "Usage: $0 [--skip-tests] [--skip-build] [--skip-bootstrap]"
            exit 1
            ;;
    esac
done

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$INFRA_DIR/.." && pwd)"

echo -e "${BLUE}=========================================="
echo "FireWatch Deployment Script"
echo "==========================================${NC}"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Infrastructure dir: $INFRA_DIR"
echo ""

# Step 1: Run Python unit tests
if [ "$SKIP_TESTS" = false ]; then
    echo -e "${BLUE}=========================================="
    echo "Step 1: Running Python Unit Tests"
    echo "==========================================${NC}"
    echo ""
    
    cd "$PROJECT_ROOT"
    
    # Check if pytest is installed
    if ! command -v pytest &> /dev/null; then
        echo -e "${YELLOW}⚠️  pytest not found. Installing test dependencies...${NC}"
        pip install pytest pytest-cov pytest-mock pytest-asyncio
    fi
    
    # Check if tests directory exists
    if [ ! -d "$PROJECT_ROOT/tests" ]; then
        echo -e "${YELLOW}⚠️  No tests directory found. Skipping Python tests.${NC}"
    else
        echo "Running pytest..."
        if pytest tests/ -v --tb=short; then
            echo -e "${GREEN}✓ All Python tests passed${NC}"
        else
            echo -e "${RED}❌ Python tests failed! Deployment aborted.${NC}"
            exit 1
        fi
    fi
    echo ""
    
    # Step 1b: Run TypeScript/CDK tests (if they exist)
    echo -e "${BLUE}=========================================="
    echo "Step 1b: Running TypeScript/CDK Tests"
    echo "==========================================${NC}"
    echo ""
    
    cd "$INFRA_DIR"
    
    # Check if node_modules exists (dependencies installed)
    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}⚠️  node_modules not found. Installing dependencies...${NC}"
        npm install
    fi
    
    # Check if there are any test files
    TEST_FILES=$(find . -name "*.test.ts" -o -name "*.spec.ts" 2>/dev/null | wc -l)
    if [ "$TEST_FILES" -eq 0 ]; then
        echo -e "${YELLOW}⚠️  No TypeScript test files found. Skipping CDK tests.${NC}"
    else
        echo "Running npm test..."
        if npm test; then
            echo -e "${GREEN}✓ All TypeScript/CDK tests passed${NC}"
        else
            echo -e "${RED}❌ TypeScript/CDK tests failed! Deployment aborted.${NC}"
            exit 1
        fi
    fi
    echo ""
else
    echo -e "${YELLOW}⚠️  Skipping tests (--skip-tests flag set)${NC}"
    echo ""
fi

# Step 2: Bootstrap CDK (if needed)
if [ "$SKIP_BOOTSTRAP" = false ]; then
    echo -e "${BLUE}=========================================="
    echo "Step 2: Checking CDK Bootstrap"
    echo "==========================================${NC}"
    echo ""
    
    cd "$INFRA_DIR"
    
    # Check if CDK is installed
    if ! command -v cdk &> /dev/null; then
        echo -e "${RED}❌ CDK CLI not found. Please install it:${NC}"
        echo "   npm install -g aws-cdk"
        exit 1
    fi
    
    # Check if already bootstrapped (by checking for CDKToolkit stack)
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    REGION=${AWS_REGION:-us-east-1}
    
    if [ -z "$ACCOUNT_ID" ]; then
        echo -e "${RED}❌ AWS credentials not configured. Please run 'aws configure'${NC}"
        exit 1
    fi
    
    # Check if bootstrap stack exists
    if aws cloudformation describe-stacks --stack-name CDKToolkit --region "$REGION" &>/dev/null; then
        echo -e "${GREEN}✓ CDK already bootstrapped${NC}"
    else
        echo "CDK not bootstrapped. Bootstrapping now..."
        if cdk bootstrap; then
            echo -e "${GREEN}✓ CDK bootstrapped successfully${NC}"
        else
            echo -e "${RED}❌ CDK bootstrap failed!${NC}"
            exit 1
        fi
    fi
    echo ""
else
    echo -e "${YELLOW}⚠️  Skipping CDK bootstrap (--skip-bootstrap flag set)${NC}"
    echo ""
fi

# Step 3: Build and push Docker images
if [ "$SKIP_BUILD" = false ]; then
    echo -e "${BLUE}=========================================="
    echo "Step 3: Building and Pushing Docker Images"
    echo "==========================================${NC}"
    echo ""
    
    cd "$INFRA_DIR"
    
    # Check if Docker is running
    if ! docker info &>/dev/null; then
        echo -e "${RED}❌ Docker is not running. Please start Docker and try again.${NC}"
        exit 1
    fi
    
    # Check if build script exists
    if [ ! -f "scripts/build-and-push.sh" ]; then
        echo -e "${RED}❌ Build script not found: scripts/build-and-push.sh${NC}"
        exit 1
    fi
    
    # Make script executable
    chmod +x scripts/build-and-push.sh
    
    echo "Running build-and-push.sh..."
    if ./scripts/build-and-push.sh; then
        echo -e "${GREEN}✓ All Docker images built and pushed successfully${NC}"
    else
        echo -e "${RED}❌ Docker build/push failed!${NC}"
        exit 1
    fi
    echo ""
else
    echo -e "${YELLOW}⚠️  Skipping Docker build (--skip-build flag set)${NC}"
    echo ""
fi

# Step 4: Deploy infrastructure
echo -e "${BLUE}=========================================="
echo "Step 4: Deploying Infrastructure"
echo "==========================================${NC}"
echo ""

cd "$INFRA_DIR"

# Synthesize first to check for errors
echo "Synthesizing CDK stack..."
if cdk synth; then
    echo -e "${GREEN}✓ CDK synthesis successful${NC}"
else
    echo -e "${RED}❌ CDK synthesis failed!${NC}"
    exit 1
fi
echo ""

# Show diff
echo "Showing CDK diff..."
cdk diff
echo ""

# Confirm deployment
echo -e "${YELLOW}⚠️  About to deploy infrastructure to AWS${NC}"
echo -e "${YELLOW}   This will create/modify AWS resources and may incur costs.${NC}"
echo ""
read -p "Continue with deployment? (yes/no): " -r
echo ""

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled by user.${NC}"
    exit 0
fi

# Deploy
echo "Deploying CDK stack..."
if cdk deploy --require-approval never; then
    echo ""
    echo -e "${GREEN}=========================================="
    echo "✓ Deployment Successful!"
    echo "==========================================${NC}"
    echo ""
    echo "Your FireWatch infrastructure is now deployed to AWS."
    echo ""
    echo "Next steps:"
    echo "  1. Check the AWS Console to verify resources"
    echo "  2. Monitor CloudWatch logs for service health"
    echo "  3. Send test videos to the pipeline"
    echo ""
else
    echo ""
    echo -e "${RED}=========================================="
    echo "❌ Deployment Failed!"
    echo "==========================================${NC}"
    echo ""
    echo "Check the error messages above for details."
    exit 1
fi

