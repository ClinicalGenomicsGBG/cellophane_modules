# HCP module for Cellophane

Fetch sample files from S3 backup (using boto3). If the backup attribute is set on a `data.Sample` this will be used as the remote keys. Otherwise, the local filenames will be used to search for matching files in the bucket.

## Configuration

Option            | Type      | Required | Default | Description
------------------|-----------|----------|---------|-------------
`s3.credentials`  | str       | x        |         | Path to s3 credentials file
`s3.fastq_temp`   | str       | x        |         | Path where fastqs will be stored
`s3.parallel`     | int       |          | 4       | Number of parallel downloads

## Hooks

Name       | When | Condition | Description
-----------|------|-----------|-------------
`s3_fetch` | Pre  |           | Fetch sample files from S3 backup

## Mixins

`S3Sample`

```
s3_remote_keys: list[str] - List of remote keys for files
s3_bucket: str = "data"   - S3 bucket name
```