/**
 * Netlify Function: Push Config
 * Returns VAPID public key and whether web push is enabled.
 *
 * Usage: GET /.netlify/functions/push-config
 * Response: { enabled: boolean, publicKey: string }
 *
 * enabled=true only when BOTH VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set.
 * This lets the client hide the push-subscribe UI until the founder has
 * generated and wired up VAPID keys in Netlify environment variables.
 */

exports.handler = async (event) => {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
  };

  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 200, headers, body: '' };
  }

  if (event.httpMethod !== 'GET') {
    return {
      statusCode: 405,
      headers,
      body: JSON.stringify({ error: 'Method not allowed' }),
    };
  }

  const publicKey  = process.env.VAPID_PUBLIC_KEY  || '';
  const privateKey = process.env.VAPID_PRIVATE_KEY || '';
  const enabled    = Boolean(publicKey && privateKey);

  return {
    statusCode: 200,
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, publicKey: enabled ? publicKey : '' }),
  };
};
