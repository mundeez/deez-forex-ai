# Election Dashboard Resolution Implementation Plan

## Problem Summary
The election dashboard is returning 500 errors on supab routes (`/api/v1/supad/tenants/{tenantId}/dashboard/*`) while other endpoints work correctly. The tenant service functions properly, indicating the issue is specific to the gateway service's handling of supab dashboard routes.

## Root Causes Identified
1. **Missing Supab User**: No users with "supab" role exist in the database
2. **Gateway Service Issue**: Gateway service fails on supab dashboard routes while tenant service works
3. **Authentication Flow**: Supab routes require "supab" role authentication that isn't properly configured
4. **Service Function Failures**: `GetDashboardSummary`, `GetElectionResultsByScope`, and `ListVerifierQueue` fail when called through gateway context

## Implementation Plan

### Phase 1: Authentication & User Setup (Immediate)
**Objective**: Enable proper supab authentication to allow debugging and testing

1. **Create Supab User**
   - Add a user with "supab" role to the `tenant_users` table
   - Set up proper authentication through Gotrue
   - Test authentication flow with new supab user

2. **Configure Authentication Tokens**
   - Generate valid JWT tokens for testing
   - Set up authentication headers for API testing
   - Verify token validation works correctly

### Phase 2: Gateway Service Debugging (High Priority)
**Objective**: Identify and fix the specific issue causing 500 errors in gateway supab routes

1. **Enhanced Error Logging**
   - Add detailed error logging in gateway service dashboard handlers
   - Log the exact error messages from service function failures
   - Add request/response logging for supab dashboard endpoints

2. **Service Function Isolation**
   - Test `GetDashboardSummary`, `GetElectionResultsByScope`, and `ListVerifierQueue` directly
   - Compare behavior between gateway and tenant service contexts
   - Identify differences in initialization or execution context

3. **Database Query Validation**
   - Test database queries used by failing functions
   - Verify query execution with actual tenant IDs
   - Check for any PostgreSQL-specific issues in gateway context

### Phase 3: Architecture Fix (Medium Priority)
**Objective**: Implement a robust solution to prevent similar issues

1. **Unified Service Architecture**
   - Consider consolidating dashboard route handling
   - Ensure consistent initialization between gateway and tenant services
   - Implement shared middleware for common functionality

2. **Graceful Degradation**
   - Add fallback mechanisms when supab routes fail
   - Implement circuit breakers for failing endpoints
   - Add retry logic for transient failures

3. **Error Handling Enhancement**
   - Standardize error responses across all services
   - Add detailed error codes and messages
   - Implement proper error propagation

### Phase 4: Testing & Validation (High Priority)
**Objective**: Ensure the fix works and prevent regressions

1. **Integration Testing**
   - Test all dashboard endpoints with proper authentication
   - Verify both kulika and persistpg tenants work correctly
   - Test cascading dropdown functionality

2. **Load Testing**
   - Test dashboard under concurrent load
   - Verify database connection pooling works correctly
   - Check for memory leaks or resource issues

3. **Edge Case Testing**
   - Test with empty data sets (like persistpg tenant)
   - Test with malformed data
   - Test authentication failure scenarios

### Phase 5: Monitoring & Observability (Medium Priority)
**Objective**: Prevent future issues through better visibility

1. **Health Check Enhancement**
   - Add database connectivity checks to health endpoints
   - Monitor service function execution times
   - Track error rates by endpoint

2. **Alerting Setup**
   - Configure alerts for 500 errors
   - Monitor database connection health
   - Track authentication failure rates

## Implementation Steps

### Step 1: Quick Fix (1-2 hours)
```bash
# Add supab user to database
docker exec bd1a05eb2e94_paravotab-postgres psql -U paravotab -d paravotab -c "
INSERT INTO tenant_users (id, tenant_id, email, role, status, created_at, updated_at)
VALUES ('user-supab-admin', 'tenant-kulika', 'supab@paravotab.com', 'supab', 'active', NOW(), NOW());
"

# Test with authentication (after setting up Gotrue)
curl -H "Authorization: Bearer <token>" http://localhost:18080/api/v1/supad/tenants/kulika/dashboard/summary
```

### Step 2: Debug Logging Enhancement (2-3 hours)
- Add logging to `handleSupadTenantDashboardSummary`, `handleSupadTenantElectionResults`, `handleSupadTenantVerifierQueue`
- Log tenant resolution results
- Log service function call results
- Add timing information

### Step 3: Service Function Testing (2-3 hours)
- Create test script to call service functions directly
- Compare gateway vs tenant service behavior
- Identify specific failure points

### Step 4: Fix Implementation (3-4 hours)
- Apply fix based on debugging results
- Test fix with both tenants
- Verify cascading dropdowns work

### Step 5: Validation (1-2 hours)
- End-to-end testing of dashboard
- Verify all scenarios work correctly
- Document the fix

## Success Criteria
- ✅ Supab dashboard endpoints return 200 status with proper authentication
- ✅ Both kulika and persistpg tenants work correctly
- ✅ Cascading dropdowns function properly
- ✅ Error messages are clear and actionable
- ✅ No 500 errors on dashboard endpoints
- ✅ System handles empty data gracefully

## Risk Assessment
- **Low Risk**: User creation and authentication setup
- **Medium Risk**: Service code changes require thorough testing
- **High Risk**: Database schema changes (not planned)

## Timeline Estimate
- **Phase 1**: 2-3 hours
- **Phase 2**: 4-6 hours  
- **Phase 3**: 6-8 hours
- **Phase 4**: 3-4 hours
- **Phase 5**: 2-3 hours
- **Total**: 17-24 hours