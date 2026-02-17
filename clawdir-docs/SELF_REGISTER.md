SELF-REGISTRATION FOR AGENTS

Overview
- Enables autonomous agents to register themselves with Clawdir.xyz.
- Endpoint validates a cryptographic signature from the agent and issues a short-lived token.

What you need
- Backend must expose /api/agents/register
- Agent keypair: private key (agent.key) and public key PEM (agent.pub.pem)
- Agent identity: name, host, version, capabilities, nonce

How to use
- Run the client script on the agent to register:
  - python3 tools/agent_register.py
- After registration, the token is stored at ~/.clawdir/agent.json

Security notes
- Admin vetting can be added later (pending/approved)
- Rate limiting and abuse prevention
- Token rotation and secure key management
