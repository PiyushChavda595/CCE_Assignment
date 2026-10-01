# CampusCare AWS Lambda Deployment Guide (Region: ap-south-1)

This guide details how to configure and deploy the CampusCare serverless backend to AWS Lambda with a Lambda Function URL, connected directly to Amazon S3 and Amazon SNS in **`ap-south-1` (Asia Pacific - Mumbai)**.

---

## 1. Architecture Overview

```
User (Browser)
      ↓
Amazon EC2 (Nginx Frontend)
      ↓
AWS Lambda Function URL (CORS Enabled)
      ↓
AWS Lambda Function (Python 3.12, ap-south-1)
      ├── Amazon S3 (Bucket: <BUCKET_NAME>)
      │     ├── reports/CC-001.json
      │     └── reports/CC-001.jpeg
      │
      └── Amazon SNS (Topic: CampusCareNotifications)
            └── Confirmed Staff Email
```

*Strict Assignment Constraints:*
- **Zero extra databases:** No RDS, DynamoDB, MongoDB, or SQL servers.
- **No API Gateway, ALB, SQS, or NAT Gateway.**
- Uses **AWS Lambda Function URL** for direct, cost-free, low-latency HTTP invocations.
- Concurrency-safe sequential Report ID generation (`CC-001`, `CC-002`, `CC-003`, …) implemented directly over S3 strong consistency.

---

## 2. AWS Resources Summary

| Resource | Service | Identifier / Name | Region |
|---|---|---|---|
| Report & Image Storage | Amazon S3 | `<BUCKET_NAME>` (e.g. `campuscare-reports-<unique-id>`) | `ap-south-1` |
| Email Alerts | Amazon SNS | `CampusCareNotifications` (Standard Topic) | `ap-south-1` |
| Serverless Handler | AWS Lambda | `CampusCareHandler` (Python 3.12) | `ap-south-1` |
| Public HTTP Endpoint | Lambda Function URL | `AuthType: NONE`, CORS: `*` | `ap-south-1` |
| Frontend Host | Amazon EC2 | `t2.micro` / `t3.micro` (Nginx) | `ap-south-1` |

---

## 3. Step-by-Step Deployment Instructions

### Step 3.1: Create Amazon S3 Bucket
#### AWS Console:
1. Open **Amazon S3** Console -> Click **Create bucket**.
2. **Bucket name**: `<BUCKET_NAME>` (e.g., `campuscare-reports-<your-name>-2026`).
3. **AWS Region**: `ap-south-1` (Asia Pacific (Mumbai)).
4. **Block Public Access**: Keep **Block *all* public access** ENABLED.
   *(Lambda securely accesses S3 via its IAM execution role and serves images via secure Presigned URLs)*.
5. Click **Create bucket**.

#### AWS CLI:
```bash
aws s3api create-bucket \
  --bucket <BUCKET_NAME> \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
```

### Step 3.2: Create Amazon SNS Topic & Confirm Email Subscription
#### AWS Console:
1. Open **Amazon SNS** Console -> **Topics** -> **Create topic**.
2. **Type**: Select **Standard**.
3. **Name**: `CampusCareNotifications`.
4. Click **Create topic**.
5. Copy the generated **Topic ARN**: `arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications`.
6. Under the topic details, click **Create subscription**:
   - **Protocol**: `Email`
   - **Endpoint**: Enter the staff/evaluator email address.
   - Click **Create subscription**.
7. **CRITICAL STEP**: Open the recipient email inbox and find the email with subject *"AWS Notification - Subscription Confirmation"*. Click **Confirm subscription**. The subscription status in AWS SNS will change from *PendingConfirmation* to **Confirmed**.

#### AWS CLI:
```bash
# 1. Create Standard Topic
aws sns create-topic \
  --name CampusCareNotifications \
  --region ap-south-1

# 2. Subscribe staff email
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications \
  --protocol email \
  --notification-endpoint <STAFF_EMAIL> \
  --region ap-south-1
```

### Step 3.3: Create IAM Execution Role for Lambda
#### AWS Console:
1. Open **IAM Console** -> **Roles** -> **Create role**.
2. **Trusted entity type**: `AWS service` -> **Use case**: `Lambda`.
3. Add the managed policy: `AWSLambdaBasicExecutionRole` (for CloudWatch Logs).
4. Add an **Inline Policy** named `CampusCarePermissions`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ReportStorageAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::<BUCKET_NAME>",
        "arn:aws:s3:::<BUCKET_NAME>/*"
      ]
    },
    {
      "Sid": "SNSPublishAccess",
      "Effect": "Allow",
      "Action": [
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications"
    }
  ]
}
```
5. **Role name**: `CampusCareLambdaRole` -> Click **Create role**.
6. Note the role ARN: `arn:aws:iam::<ACCOUNT_ID>:role/CampusCareLambdaRole`.

#### AWS CLI:
```bash
# 1. Create trust policy file trust.json:
# {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}

# 2. Create Role:
aws iam create-role \
  --role-name CampusCareLambdaRole \
  --assume-role-policy-document file://trust.json

# 3. Attach basic logging:
aws iam attach-role-policy \
  --role-name CampusCareLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# 4. Attach S3 & SNS permissions (save policy above to policy.json):
aws iam put-role-policy \
  --role-name CampusCareLambdaRole \
  --policy-name CampusCarePermissions \
  --policy-document file://policy.json
```

### Step 3.4: Package and Upload Lambda Function
Package the Lambda backend locally:
```powershell
python deployment\lambda\package_lambda.py
```
This generates `deployment/dist/campuscare_lambda.zip` (~9 KB).

#### AWS Console:
1. Open **AWS Lambda Console** -> Click **Create function**.
2. **Function name**: `CampusCareHandler`.
3. **Runtime**: `Python 3.12`.
4. **Architecture**: `x86_64`.
5. **Permissions**: Choose **Use an existing role** -> Select `CampusCareLambdaRole`.
6. Click **Create function**.
7. In the **Code** tab -> Click **Upload from** -> **.zip file** -> Select `deployment/dist/campuscare_lambda.zip`.
8. Under **Runtime settings**, verify:
   - **Handler**: `lambda_function.lambda_handler`
9. In **Configuration** -> **General configuration**:
   - **Timeout**: `15 sec`
   - **Memory**: `256 MB`

#### AWS CLI:
```bash
aws lambda create-function \
  --function-name CampusCareHandler \
  --runtime python3.12 \
  --role arn:aws:iam::<ACCOUNT_ID>:role/CampusCareLambdaRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://deployment/dist/campuscare_lambda.zip \
  --timeout 15 \
  --memory-size 256 \
  --region ap-south-1
```

### Step 3.5: Configure Environment Variables
In Lambda -> **Configuration** -> **Environment variables** -> **Edit**:
- `S3_BUCKET_NAME` = `<BUCKET_NAME>`
- `SNS_TOPIC_ARN` = `arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications`
- `AWS_REGION` = `ap-south-1`
- `CORS_ALLOW_ORIGIN` = `*`
Click **Save**.

CLI equivalent:
```bash
aws lambda update-function-configuration \
  --function-name CampusCareHandler \
  --environment "Variables={S3_BUCKET_NAME=<BUCKET_NAME>,SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications,AWS_REGION=ap-south-1,CORS_ALLOW_ORIGIN=*}" \
  --region ap-south-1
```

### Step 3.6: Configure Lambda Function URL & CORS
#### AWS Console:
1. In the Lambda function -> **Configuration** -> **Function URL** -> Click **Create function URL**.
2. **Auth type**: Select **NONE**.
3. Check **Configure cross-origin resource sharing (CORS)**:
   - **Allow origin**: `*`
   - **Allow methods**: `GET`, `POST`, `OPTIONS`
   - **Allow headers**: `content-type`, `authorization`, `x-requested-with`
   - **Max age**: `86400`
4. Click **Save**.
5. Copy the generated **Function URL**:
   `https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws/`

#### AWS CLI:
```bash
# 1. Create Function URL
aws lambda create-function-url-config \
  --function-name CampusCareHandler \
  --auth-type NONE \
  --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST","OPTIONS"],"AllowHeaders":["content-type","authorization","x-requested-with"],"MaxAge":86400}' \
  --region ap-south-1

# 2. Add public invoke permission
aws lambda add-permission \
  --function-name CampusCareHandler \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region ap-south-1
```

---

## 4. Test the Lambda Function URL Directly

Using curl:
```bash
# Test GET reports list (should return [] on fresh bucket)
curl -X GET https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws/api/reports

# Test OPTIONS CORS preflight
curl -i -X OPTIONS https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws/api/reports
```
