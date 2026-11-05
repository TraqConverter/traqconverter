<?php
// Reverse proxy to the Next.js process. Apache on this host has no
// mod_proxy_http and we have no root, so PHP does the hop. Static files are
// served by Apache directly (see .htaccess) and never reach this script.
$upstream = 'http://127.0.0.1:3100';
$uri = $_SERVER['REQUEST_URI'] ?? '/';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$contentType = $_SERVER['CONTENT_TYPE'] ?? '';

$body = null;
if ($method !== 'GET' && $method !== 'HEAD') {
    $body = file_get_contents('php://input');
    // With enable_post_data_reading on (user.ini not yet picked up by FPM),
    // php://input is empty because PHP already parsed the body. Rebuild the
    // multipart payload from what it parsed so uploads still reach Node.
    if (($body === '' || $body === false) && ($_POST || $_FILES)) {
        $boundary = '----odt' . bin2hex(random_bytes(12));
        $parts = '';
        $walk = function ($name, $value) use (&$walk, &$parts, $boundary) {
            if (is_array($value)) {
                foreach ($value as $k => $v) $walk($name . '[' . $k . ']', $v);
                return;
            }
            $parts .= "--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n";
        };
        foreach ($_POST as $name => $value) $walk($name, $value);
        foreach ($_FILES as $name => $f) {
            $names = is_array($f['name']) ? $f['name'] : [$f['name']];
            $tmps = is_array($f['tmp_name']) ? $f['tmp_name'] : [$f['tmp_name']];
            $types = is_array($f['type']) ? $f['type'] : [$f['type']];
            $errs = is_array($f['error'] ?? null) ? $f['error'] : [$f['error'] ?? UPLOAD_ERR_OK];
            foreach ($names as $i => $fn) {
                // A file PHP rejected (over upload_max_filesize, partial write)
                // arrives with an empty tmp_name. Skipping it quietly is how a
                // customer attached four documents, saw "Thank you", and we
                // received none of them with nothing in any log to say so.
                if ($fn && ($errs[$i] ?? UPLOAD_ERR_OK) !== UPLOAD_ERR_OK) {
                    error_log(sprintf(
                        'ctuk-proxy: dropped upload "%s" (PHP upload error %d; upload_max_filesize=%s post_max_size=%s)',
                        $fn, $errs[$i], ini_get('upload_max_filesize'), ini_get('post_max_size')
                    ));
                }
                if (!$fn || !is_uploaded_file($tmps[$i])) continue;
                $data = file_get_contents($tmps[$i]);
                $ct = $types[$i] ?: 'application/octet-stream';
                $fn = str_replace('"', '', $fn);
                $parts .= "--$boundary\r\nContent-Disposition: form-data; name=\"$name\"; filename=\"$fn\"\r\n"
                    . "Content-Type: $ct\r\n\r\n" . $data . "\r\n";
            }
        }
        $body = $parts . "--$boundary--\r\n";
        $contentType = "multipart/form-data; boundary=$boundary";
    }
}

$headers = [];
foreach ($_SERVER as $k => $v) {
    if (strpos($k, 'HTTP_') === 0) {
        $name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($k, 5)))));
        if (in_array(strtolower($name), ['host', 'connection', 'accept-encoding', 'content-length', 'content-type', 'transfer-encoding', 'expect'], true)) continue;
        $headers[] = "$name: $v";
    }
}
if ($contentType !== '') $headers[] = 'Content-Type: ' . $contentType;
if ($body !== null) $headers[] = 'Content-Length: ' . strlen($body);
$host = $_SERVER['HTTP_HOST'] ?? 'certifiedtranslationsuk.com';
$headers[] = "Host: $host";
$headers[] = 'X-Forwarded-Host: ' . $host;
$headers[] = 'X-Forwarded-Proto: ' . ((!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https' ? 'https' : 'http');
$headers[] = 'X-Forwarded-For: ' . ($_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? '');
$headers[] = 'Accept-Encoding: identity';
$headers[] = 'Expect:';

$ch = curl_init($upstream . $uri);
curl_setopt_array($ch, [
    CURLOPT_CUSTOMREQUEST => $method,
    CURLOPT_HTTPHEADER => $headers,
    CURLOPT_HEADER => false,
    CURLOPT_RETURNTRANSFER => false,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 5,
    CURLOPT_TIMEOUT => 120,
    CURLOPT_HEADERFUNCTION => function ($ch, $line) {
        $t = trim($line);
        if ($t === '') return strlen($line);
        if (stripos($t, 'HTTP/') === 0) {
            $code = (int) explode(' ', $t)[1];
            http_response_code($code);
            return strlen($line);
        }
        $lower = strtolower(strtok($t, ':'));
        if (in_array($lower, ['transfer-encoding', 'connection', 'keep-alive', 'content-encoding', 'content-length'], true)) return strlen($line);
        header($t, false);
        return strlen($line);
    },
    CURLOPT_WRITEFUNCTION => function ($ch, $chunk) {
        echo $chunk;
        flush();
        return strlen($chunk);
    },
]);
if ($body !== null) curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
if ($method === 'HEAD') curl_setopt($ch, CURLOPT_NOBODY, true);

if (curl_exec($ch) === false) {
    http_response_code(502);
    header('Content-Type: text/html; charset=utf-8');
    header('Retry-After: 10');
    echo '<!doctype html><title>Temporarily unavailable</title><p>The site is restarting. Please retry in a moment.</p>';
}
curl_close($ch);
