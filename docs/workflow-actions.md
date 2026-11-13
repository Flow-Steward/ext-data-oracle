# Oracle workflow actions

Configure the Oracle host and service_name, port (default 1521), verified TLS and secret username/password. Set allow_writes=true only for a connection intended to modify rows, with corresponding database permissions. Private endpoints need the Flow Steward administrator to permit private remote URLs.

## Read rows

Choose **Oracle: Read rows with a SELECT query**, select the project connection and enter:

```sql
SELECT order_id, status FROM orders WHERE status = :1
```

Set **Positional parameter values (JSON array)** to:

```json
["approved"]
```

This reads a bounded result for the next workflow step. Set Maximum returned rows to 10 for an initial preview (maximum 100); result.records contains the returned rows.

## Write workflow results

Choose **Oracle: Insert, update, delete or merge rows**, select the connection and enter:

```sql
UPDATE orders SET status = :1 WHERE order_id = :2
```

Supply these parameters, binding values from previous steps as needed:

```json
["approved",1042]
```

One INSERT, UPDATE, DELETE or MERGE is supported. Oracle writes require allow_writes=true in the connection.
Do not interpolate values into SQL, submit multi-statement scripts or use DDL.
Test mode suppresses writes. A transport failure can leave a write outcome uncertain;
inspect the database before manually repeating it.

Parameters are an array of scalar values, not named objects. The first value binds :1, the second :2. A write does not automatically create a missing row; use the appropriate INSERT or MERGE for that case.
