<?php

declare(strict_types=1);

require __DIR__ . '/checkout-lib.php';

$code = is_string($_GET['code'] ?? null) ? $_GET['code'] : '';
$checkout = \Harness\checkout($code);

if (($_GET['format'] ?? null) === 'json') {
    header('Content-Type: application/json');
    echo json_encode($checkout, JSON_THROW_ON_ERROR);
    return;
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PHP debugging harness</title>
</head>
<body>
    <h1>PHP debugging harness</h1>
    <p>Enter SAVE10 to apply a £10 discount to a £100 order.</p>
    <form method="get">
        <label for="code">Discount code</label>
        <input id="code" name="code" value="<?= htmlspecialchars($code, ENT_QUOTES, 'UTF-8') ?>">
        <button type="submit">Apply</button>
    </form>
    <p>Total: <output data-testid="total">£<?= $checkout['total'] ?></output></p>
    <p><a href="/health.php">Runtime details</a></p>
</body>
</html>
