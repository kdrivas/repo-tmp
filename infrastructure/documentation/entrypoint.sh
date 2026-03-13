#!/bin/sh
# Modify Nginx configuration to listen on the specified port to honor Google Cloud Run's PORT environment variable.

export PORT="${PORT:-8080}"
export MODE="${MODE:-multi}"
export DEFAULT_REDIRECT="${DEFAULT_REDIRECT:-repo-template}"

echo "Removing default configuration (/etc/nginx/conf.d/default.conf) that we won't use."
rm /etc/nginx/conf.d/default.conf

echo "Configuring nginx for MODE=${MODE}."
if [ "$MODE" = "multi" ]; then
    # Clean up slashes from the DEFAULT_REDIRECT variable to avoid issues.
    DEFAULT_REDIRECT=$(echo "${DEFAULT_REDIRECT}" | sed 's|^/*||;s|/*$||')
    # Use a 307 instead of 301 to avoid caching issues in browsers if stuff changes. Not a 302 to ensure the GET method is preserved.
    REDIRECT_CONFIG="    # Redirects traffic from documentation.tryolabs.com/ to the default site.
    location = / {
        return 307 /${DEFAULT_REDIRECT}/;
    }
";
    echo "Multi mode: static sites should be mounted to /var/www/sites/<site_name>."
else
    REDIRECT_CONFIG="";
    echo "Single mode: static site should be mounted to /var/www/sites."
fi

echo "$REDIRECT_CONFIG" | sed -e "/\${REDIRECT_CONFIG}/r /dev/stdin" -e "/\${REDIRECT_CONFIG}/d" /tmp/nginx.conf.template > /etc/nginx/conf.d/nginx.conf

echo "Changing listening port from 80 to ${PORT} in /etc/nginx/conf.d/nginx.conf."
sed -i "s/listen[[:space:]]\+80;/listen ${PORT};/g" /etc/nginx/conf.d/nginx.conf

echo "Starting Nginx in the foreground."
exec nginx -g 'daemon off;'