<div align="justify">
  
# Space Medical Monitoring
## NASA Space Crew Monitoring System
An Integrated Health Monitoring, Medical Record Management, and Emergency Response Platform for Space Missions

## Project Overview
The NASA Space Crew Monitoring System is an interactive monitoring platform designed to support astronaut health management and crew safety during space missions.

Developed using Python and Streamlit, the system integrates biometric monitoring, medical record management, preventive health indicators, radiation exposure tracking, and emergency response protocols into a unified interface.

The platform provides a centralized environment for monitoring crew members, analyzing health-related data, identifying potential medical alerts, and supporting communication with Mission Control.

## Main Objectives
* Monitor astronaut health indicators and physiological parameters.
* Track radiation exposure and cumulative radiation levels.
* Monitor cardiovascular, respiratory, ocular, thermal, and musculoskeletal indicators.
* Evaluate exercise compliance and bone mineral density changes.
* Maintain organized medical records for each crew member.
* Identify abnormal measurements and generate automated alerts.
* Provide structured emergency response protocols.
* Support communication and incident reporting with Mission Control.

## Main Features
### 1. Crew and Mission Management
- Create and manage space missions.
- Register crew members and their basic information.
- Associate astronauts with specific missions.
- Store pre-mission baseline bone mineral density measurements.
### 2. Biometric & Medical Monitoring
The system provides an interactive anatomical interface that allows users to select different monitoring zones.

##### Monitoring Zone	Parameters
<div align="center"> 
  
|Body Part| Parameters|
|:-----:|:-----:|
| Forehead 	|Mood, sleep duration, radiation exposure|
| Eyes	|Ocular health assessments and medical images|
| Nose	|Oxygenation-related measurements|
| Heart	|Heart rate, systolic and diastolic blood pressure, pulse pressure|
| Hand	|Temperature and skin symptoms|
| Leg	|Exercise duration and bone mineral density|

</div>

### 3. Preventive Health Monitoring
The platform includes monitoring indicators and reference thresholds for:

* Radiation exposure.
* Sleep duration and psychological well-being.
* Cardiovascular parameters.
* Thermal conditions.
* Exercise compliance.
* Bone mineral density.
### 4. Automated Emergency Detection
The system evaluates recorded measurements against configured thresholds and can automatically redirect the interface to the emergency management module.

Supported emergency categories include:

* Cardiac Emergency
* Respiratory Emergency
* Loss of Consciousness
* Trauma / Injury
* Burns
* Seizure
* Psychological Emergency
* Other Emergency

### 5. Emergency Response & Mission Control
The emergency module provides:

* Step-by-step emergency response guidance.
* Actions to avoid during critical incidents.
* Vital signs registration.
* Emergency communication report generation.
* Automatic emergency information transfer from biometric alerts.
* Emergency incident history.
* CSV report export.
* Text-to-speech functionality for reading emergency protocols aloud.

### 6. Clinical History & Data Visualization
Using Plotly, the platform provides interactive clinical charts to visualize recorded measurements over time.

Features include:

* Historical biometric records.
* Crew-specific health trends.
* Temperature monitoring reference zones.
* Bone density monitoring thresholds.
* Daily exercise target visualization.
* Mood and sleep history.
* Medical image history.

### Technologies Used
<div align="center"> 
  
|Technology	|Purpose|
|:-----:|:-----:|
|Python	|Main programming language|
|Streamlit	|Interactive web application framework|
|Pandas	|Medical records and data management|
|NumPy	|Numerical operations|
|Plotly	|Interactive data visualization|
|Pillow (PIL)	|Medical and anatomical image processing|
|Base64	|Image encoding|
|JSON	|Structured data handling|
|HTML / CSS	|Interface customization|
|JavaScript	|Text-to-speech functionality|
</div>

###  Technical Approach
The platform uses a centralized session-state architecture to manage crew information, medical records, mission data, and emergency events.

Biometric measurements are stored in structured Pandas DataFrames, while custom functions extract numerical indicators from recorded metrics and evaluate them against predefined thresholds.

Plotly provides interactive anatomical selection and historical data visualization, while Streamlit manages the application's interface and navigation.

The emergency management module integrates automated alerts with predefined response protocols and structured communication reports.

</div>
