# CampusCare — Campus Issue Reporting & Resolution Portal

[![Cloud Architecture: EC2 + Lambda + S3 + SNS](https://img.shields.io/badge/Architecture-EC2%20%7C%20Lambda%20%7C%20S3%20%7C%20SNS-4f46e5?style=flat-square)](https://aws.amazon.com/)
[![AWS Region: ap-south-1](https://img.shields.io/badge/AWS%20Region-ap--south--1-ff9900?style=flat-square)](https://aws.amazon.com/)
[![Runtime: Python 3.12](https://img.shields.io/badge/Runtime-Python%203.12-38bdf8?style=flat-square)](https://python.org/)
[![Database: Zero Extra Databases](https://img.shields.io/badge/Database-Zero%20Extra%20DBs%20(Serverless%20S3)-10b981?style=flat-square)]()

**CampusCare** is a modern, responsive campus technology platform for reporting and resolving facility issues, cleanliness concerns, campus complaints, suggestions, and lost & found items. It directly connects students and faculty to campus staff through automated email dispatch and cloud storage.

---

## 1. Project Overview

CampusCare allows campus members to submit reports with:
- **Report Type**: `Maintenance`, `Cleanliness`, `Complaint`, `Suggestion`, `Lost & Found`, or `Other`
- **Title**: A concise summary of the issue
- **Location**: Specific campus hall, laboratory, or building
- **Description**: Detailed context
- **Reporter Information**: Name and email address
- **Optional Photo Evidence**: JPG, JPEG, PNG, or WEBP (up to 5 MB)

Upon submission:
1. The system assigns a sequential **Report ID** (`CC-001`, `CC-002`, `CC-003`, …) using a concurrency-safe atomic claim mechanism.
2. Report metadata is saved as JSON in Amazon S3 (`reports/CC-XXX.json`), and uploaded photos are stored in S3 (`reports/CC-XXX.ext`).
3. An automated email alert is dispatched via **Amazon SNS** to the designated campus response staff.
4. The report instantly appears in the live campus feed with search, category filtering, and full detail inspection.

---

## 2. AWS Production Architecture

The application strictly conforms to the required Cloud Computing assignment constraints:

```
                          ┌───────────────────────────┐
                          │       User Browser        │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │        Amazon EC2         │
                          │   (Nginx Web Server)      │
                          │  CampusCare Static Assets │
                          └─────────────┬─────────────┘
                                        │
                                        ▼ HTTPS (CORS)
                          ┌───────────────────────────┐
                          │  AWS Lambda Function URL  │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │    AWS Lambda Function    │
                          │ (Python 3.12, ap-south-1) │
                          └──────┬─────────────┬──────┘
                                 │             │
                S3 PutObject/Get │             │ SNS Publish
                                 ▼             ▼
         ┌─────────────────────────┐     ┌─────────────────────────┐
         │        Amazon S3        │     │       Amazon SNS        │
         │     (<BUCKET_NAME>)     │     │ CampusCareNotifications │
         ├─────────────────────────┤     └─────────────┬───────────┘
         │ reports/CC-001.json     │                   │
         │ reports/CC-001.jpeg     │                   ▼ Email
         │ reports/CC-002.json     │     ┌─────────────────────────┐
         │ reports/CC-002.jpeg     │     │  Confirmed Staff Email  │
         └─────────────────────────┘     └─────────────────────────┘
```

### Strict Constraint Checklist
- [x] **Amazon EC2**: Hosts the production frontend via Nginx.
- [x] **AWS Lambda**: Serverless backend handler (zero idle server cost).
- [x] **Lambda Function URL**: Direct HTTP invocations (`AuthType: NONE`).
- [x] **Amazon S3**: Atomic JSON and image asset storage.
- [x] **Amazon SNS**: Email notifications to verified staff subscribers.
- [x] **Single AWS Region**: `ap-south-1` used consistently across S3, Lambda, SNS, and EC2.
- [x] **NO RDS or DynamoDB**: Avoids extra databases.
- [x] **NO API Gateway, ALB, SQS, or NAT Gateway**: Lightweight and cost-effective.
- [x] **Concurrency-Safe Sequential IDs**: Atomic S3 reservation prevents ID collision without extra databases.
- [x] **Dual Mode Support**: Seamless toggle between local development and AWS production.

---

## 3. Project Directory Structure

```text
CampusCare/
├── README.md                      # Comprehensive deployment & demo documentation
├── requirements.txt               # Local Python dependencies (Flask, Flask-CORS)
├── structure.txt                  # Directory structure snapshot
├── .gitignore                     # Git ignore rules
├── .env.example                   # Environment configuration template (ap-south-1)
│
├── backend/                       # Local Development Backend (Flask)
│   ├── app.py                     # Local REST API endpoints
│   ├── services/
│   │   ├── storage_service.py     # Local filesystem storage
│   │   └── notification_service.py# Local console & file notification
│   └── utils/
│       └── report_id.py           # Report ID validation utility
│
├── lambda/                        # AWS Production Backend (Serverless Lambda)
│   ├── lambda_function.py         # Main Function URL handler (GET, POST, OPTIONS)
│   ├── services/
│   │   ├── s3_service.py          # S3 report JSON & image manager + concurrency lock
│   │   └── sns_service.py         # SNS topic publisher (ap-south-1)
│   └── utils/
│       └── report_id.py           # Report ID generator & validator
│
├── frontend/                      # Production-grade Web Application
│   ├── index.html                 # Semantic HTML5, accessibility & modals
│   ├── style.css                  # Modern responsive design system
│   ├── script.js                  # Frontend controller & real-time filter engine
│   └── config.js                  # Dynamic API endpoint configuration
│
├── deployment/                    # Deployment Automation
│   ├── ec2/
│   │   ├── deploy.sh              # Automated EC2 Nginx setup script
│   │   └── nginx.conf             # Production Nginx site configuration
│   ├── lambda/
│   │   ├── package_lambda.py      # Automated zip builder (<10 KB output)
│   │   └── README.md              # Detailed AWS console & CLI walkthrough
│   └── dist/
│       └── campuscare_lambda.zip  # Production Lambda deployment bundle
│
├── storage/                       # Local Development Storage Directory
│   └── reports/                   # Persisted local JSON and images
│
└── tests/                         # Automated Unit Tests
    ├── __init__.py
    └── test_lambda.py             # 15 automated tests (concurrency, S3, SNS, Lambda)
```

---

## 4. Concurrency Protection & Report ID Generation

### How Collisions Are Prevented in Amazon S3
In AWS Lambda, multiple users may submit reports simultaneously. Without a database, naive implementations suffer from race conditions where two Lambda invocations see the same highest number and overwrite each other's reports.

CampusCare prevents this entirely within **Amazon S3** using S3's strong read-after-write consistency:
1. **Candidate Selection**: Lambda lists existing report keys (`reports/CC-*.json`) to find the highest number $N$, setting the candidate ID to `CC-{N+1:03d}`.
2. **Atomic Lock File**: Lambda writes a unique lock object:
   `reports/.locks/CC-{candidate}_{lock_uuid}.lock`
3. **Consistency Check**: Lambda immediately lists all objects with prefix `reports/.locks/CC-{candidate}_`.
4. **Deterministic Tie-Breaker**:
   - If only one lock exists, this invocation owns the ID.
   - If concurrent invocations wrote locks for the same ID, the invocation with the lowest lexicographical UUID wins.
   - The losing invocation deletes its lock, increments candidate ID to $N+2$, applies randomized jitter (50–150ms), and retries.
5. **Lock Cleanup**: Once the report JSON and image are uploaded to `reports/CC-{candidate}.json`, the temporary lock file is deleted.
6. **Zero Database Needed**: Guarantees unique sequential IDs (`CC-001`, `CC-002`, `CC-003`, ...) even under concurrent load without DynamoDB or RDS.

---

## 5. Local Development Quickstart (Verified)

You can run and test the complete application locally without an active AWS account:

```powershell
# 1. Start local Flask API (Terminal 1)
python backend\app.py

# 2. Serve frontend (Terminal 2)
python -m http.server 8000 --directory frontend
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

Run automated unit tests:
```powershell
python tests\test_lambda.py
```
*(Result: 15/15 tests passing).*

---

## 6. Real AWS Deployment Guide (Step-by-Step 1 to 20)

Follow these exact steps to deploy CampusCare to AWS in **`ap-south-1`**:

### STEP 1: Create S3 Bucket
- **AWS Console**: Open **Amazon S3** &rarr; **Create bucket** &rarr; Name: `<BUCKET_NAME>` (e.g. `campuscare-reports-john-2026`) &rarr; Region: `ap-south-1` &rarr; Keep **Block *all* public access** enabled &rarr; Click **Create bucket**.
- **CLI**:
  ```bash
  aws s3api create-bucket \
    --bucket <BUCKET_NAME> \
    --region ap-south-1 \
    --create-bucket-configuration LocationConstraint=ap-south-1
  ```

### STEP 2: Create SNS Topic
- **AWS Console**: Open **Amazon SNS** &rarr; **Topics** &rarr; **Create topic** &rarr; Type: **Standard** &rarr; Name: `CampusCareNotifications` &rarr; Click **Create topic**.
- **CLI**:
  ```bash
  aws sns create-topic \
    --name CampusCareNotifications \
    --region ap-south-1
  ```
  *(Save the Topic ARN: `arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications`)*.

### STEP 3: Confirm SNS Email Subscription
- **AWS Console**: In `CampusCareNotifications` topic &rarr; **Create subscription** &rarr; Protocol: `Email` &rarr; Endpoint: `<STAFF_EMAIL>` &rarr; Click **Create subscription**.
- **CLI**:
  ```bash
  aws sns subscribe \
    --topic-arn arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications \
    --protocol email \
    --notification-endpoint <STAFF_EMAIL> \
    --region ap-south-1
  ```
- **CRITICAL**: Check the inbox of `<STAFF_EMAIL>`. Open the email from *AWS Notifications* and click **Confirm subscription**. The subscription status in SNS must display **Confirmed**.

### STEP 4: Create IAM Role for Lambda
- **AWS Console**: Open **IAM** &rarr; **Roles** &rarr; **Create role** &rarr; Trusted entity: **AWS service** &rarr; Use case: **Lambda**.
- Attach managed policy: `AWSLambdaBasicExecutionRole`.
- Add inline policy named `CampusCarePolicy`:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "S3StorageAccess",
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
        "Sid": "SNSPublishAlerts",
        "Effect": "Allow",
        "Action": [
          "sns:Publish"
        ],
        "Resource": "arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications"
      }
    ]
  }
  ```
- Role Name: `CampusCareLambdaRole` &rarr; Click **Create role**.

### STEP 5: Upload Lambda ZIP
- First build the zip locally:
  ```powershell
  python deployment\lambda\package_lambda.py
  ```
  *(Builds `deployment/dist/campuscare_lambda.zip` ~9 KB).*
- **AWS Console**: Open **AWS Lambda** &rarr; **Create function** &rarr; Name: `CampusCareHandler` &rarr; Runtime: `Python 3.12` &rarr; Role: Use existing role &rarr; Select `CampusCareLambdaRole` &rarr; Click **Create function**.
- In the **Code** tab &rarr; **Upload from** &rarr; **.zip file** &rarr; Upload `deployment/dist/campuscare_lambda.zip`.
- Verify Runtime settings: Handler = `lambda_function.lambda_handler`.
- **CLI**:
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

### STEP 6: Set Lambda Environment Variables
- **AWS Console**: In `CampusCareHandler` &rarr; **Configuration** &rarr; **Environment variables** &rarr; **Edit**:
  - `S3_BUCKET_NAME`: `<BUCKET_NAME>`
  - `SNS_TOPIC_ARN`: `arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications`
  - `AWS_REGION`: `ap-south-1`
  - `CORS_ALLOW_ORIGIN`: `*`
  Click **Save**.
- **CLI**:
  ```bash
  aws lambda update-function-configuration \
    --function-name CampusCareHandler \
    --environment "Variables={S3_BUCKET_NAME=<BUCKET_NAME>,SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:<ACCOUNT_ID>:CampusCareNotifications,AWS_REGION=ap-south-1,CORS_ALLOW_ORIGIN=*}" \
    --region ap-south-1
  ```

### STEP 7: Create Lambda Function URL
- **AWS Console**: In `CampusCareHandler` &rarr; **Configuration** &rarr; **Function URL** &rarr; Click **Create function URL**.
- Auth type: **NONE**.
- Check **Configure cross-origin resource sharing (CORS)**:
  - Allow origin: `*`
  - Allow methods: `GET`, `POST`, `OPTIONS`
  - Allow headers: `content-type`, `authorization`, `x-requested-with`
  - Max age: `86400`
- Click **Save**. Copy the generated URL: `https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws/`.
- **CLI**:
  ```bash
  aws lambda create-function-url-config \
    --function-name CampusCareHandler \
    --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST","OPTIONS"],"AllowHeaders":["content-type","authorization","x-requested-with"],"MaxAge":86400}' \
    --region ap-south-1

  aws lambda add-permission \
    --function-name CampusCareHandler \
    --statement-id FunctionURLAllowPublicAccess \
    --action lambda:InvokeFunctionUrl \
    --principal "*" \
    --function-url-auth-type NONE \
    --region ap-south-1
  ```

### STEP 8: Test Lambda Function URL
Using terminal curl:
```bash
curl -i -X GET https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws/api/reports
```
*Expected response: HTTP 200 OK with `[]` (empty JSON array on a fresh bucket).*

### STEP 9: Create EC2 Instance
- **AWS Console**: Open **EC2** &rarr; **Launch instance** &rarr; Name: `CampusCare-Web` &rarr; AMI: **Amazon Linux 2023** &rarr; Instance type: `t2.micro` (or `t3.micro`) &rarr; Key pair: Select or create your key pair.
- Region: `ap-south-1`.

### STEP 10: Configure Security Group
- In EC2 Launch Instance / Security Groups, ensure Inbound Rules include:
  - **SSH (Port 22)**: Source `My IP` (or `0.0.0.0/0`)
  - **HTTP (Port 80)**: Source `0.0.0.0/0` (Anywhere)
- Click **Launch instance**. Note `<EC2_PUBLIC_IP>`.

### STEP 11: Install Nginx on EC2
SSH into the EC2 instance:
```bash
ssh -i <YOUR_KEY>.pem ec2-user@<EC2_PUBLIC_IP>
```
Install Nginx:
```bash
sudo dnf update -y
sudo dnf install -y nginx
```

### STEP 12: Upload Frontend to EC2
From your local machine terminal:
```bash
scp -i <YOUR_KEY>.pem -r frontend/ ec2-user@<EC2_PUBLIC_IP>:~/CampusCare/frontend/
scp -i <YOUR_KEY>.pem -r deployment/ ec2-user@<EC2_PUBLIC_IP>:~/CampusCare/deployment/
```

### STEP 13: Configure Production Lambda URL
In `frontend/config.js` on the EC2 instance (or before uploading):
Set:
```javascript
const CAMPUSCARE_CONFIG = {
  DEFAULT_API_URL: "https://<LAMBDA_FUNCTION_URL_ID>.lambda-url.ap-south-1.on.aws",
  ...
};
```
*(Alternatively, you can configure it live in the browser via the Endpoint Badge UI or `?api=...`)*.

### STEP 14: Start Nginx
On the EC2 instance, run the automated deployment script:
```bash
cd ~/CampusCare
chmod +x deployment/ec2/deploy.sh
./deployment/ec2/deploy.sh
```
*Script deploys `/var/www/campuscare/frontend`, writes Nginx config, tests syntax, and restarts Nginx.*

### STEP 15: Open EC2 Public IP
Open your web browser and navigate to:
```text
http://<EC2-PUBLIC-IP>
```
The CampusCare portal loads with hero, category cards, statistics, and live feed.

### STEP 16: Submit Real Report
- Select **Cleanliness**.
- Title: `Garbage left on bench`.
- Location: `Block B Corridor`.
- Description: `Food wrappers and plastic bottles left unattended.`.
- Name: `Priya Patel`.
- Email: `priya@example.com`.
- Attach an image (JPG/PNG).
- Click **Submit Report**.
- Progress timeline runs &rarr; Green checkmark &rarr; **Report ID: CC-001**.

### STEP 17: Verify S3 JSON
- Open **Amazon S3 Console** in `<BUCKET_NAME>`.
- Open `reports/` folder.
- Confirm object **`CC-001.json`** is present. Download or view it to verify all fields.

### STEP 18: Verify S3 Image
- In `<BUCKET_NAME>/reports/`, confirm **`CC-001.jpg`** (or `.png`) is present.
- Verify file size matches uploaded image.

### STEP 19: Verify SNS Email
- Check the inbox of `<STAFF_EMAIL>`.
- An email alert will be present:
  - Subject: `New CampusCare Report: CC-001 [Cleanliness]`
  - Body: Contains Report ID, Type, Title, Location, Reporter details, and Description.

### STEP 20: Verify Report Appears in CampusCare
- In the browser on `http://<EC2-PUBLIC-IP>`, scroll to **Previously Submitted Reports**.
- Confirm `CC-001` appears with image thumbnail, Cleanliness badge, and timestamp.
- Click **View Details** to open the full modal.

---

## 7. Real-World Demonstration Test Plan

Execute these two standard tests to prove end-to-end functionality to your evaluator:

### TEST 1: Cleanliness Report
- **Category**: Cleanliness
- **Title**: `Garbage left on bench`
- **Location**: `Block B Corridor`
- **Description**: `Food wrappers and empty bottles left on student bench.`
- **Reporter**: `Rahul Sharma` (`rahul@example.com`)
- **Photo**: Attach small JPG/PNG
- **Verification Flow**:
  1. Frontend submission &rarr; Modal displays **`Report ID: CC-001`**.
  2. S3 bucket contains `reports/CC-001.json` and `reports/CC-001.jpeg`.
  3. SNS email received by staff member with Subject `New CampusCare Report: CC-001 [Cleanliness]`.
  4. Active reports feed lists `CC-001` at the top.

### TEST 2: Lost & Found Report
- **Category**: Lost & Found
- **Title**: `Found black wallet`
- **Location**: `Cafeteria`
- **Description**: `Black leather wallet found near table 4.`
- **Reporter**: `Priya Patel` (`priya@example.com`)
- **Photo**: Optional photo
- **Verification Flow**:
  1. Frontend submission &rarr; Modal displays sequential **`Report ID: CC-002`**.
  2. S3 bucket contains `reports/CC-002.json`.
  3. SNS email received by staff member with Subject `New CampusCare Report: CC-002 [Lost & Found]`.
  4. Active reports feed shows `CC-002` above `CC-001` (newest first).
  5. Search bar: Type `wallet` &rarr; Only `CC-002` displays.
  6. Category filters: Click `Cleanliness` &rarr; Only `CC-001` displays. Click `All` &rarr; Both display.
