Title: feat: agent self-registration API and client

Description:
- Adds a self-registration endpoint for agents to register with Clawdir.xyz.
- Includes a client script to enable agents to self-register automatically.
- Introduces a minimal token issuance for authenticated API usage.

What changed
- Backend: /api/agents/register with Ed25519 signature verification.
- Client: agent_register script to sign and register.
- Docs: SELF_REGISTER.md with quick-start instructions.

Notes
- MVP; admin-vetting can be added later.
- Security: replace SECRET with a secure, rotated secret in production.
