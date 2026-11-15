<div align="justify">
  
# Space-Medical-Monitoring
An interactive space crew health monitoring platform built with Python and Streamlit. Features biometric tracking, medical records, radiation monitoring, preventive health analytics, and automated emergency response protocols for space missions.
## NASA Space Crew Monitoring System
### An Integrated Health Monitoring, Medical Record Management, and Emergency Response Platform for Space Missions

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
  
|Body Part| Parameters|
|:-----:|:-----:|
| Forehead 	|Mood, sleep duration, radiation exposure|
| Eyes	|Ocular health assessments and medical images|
| Nose	|Oxygenation-related measurements|
| Heart	|Heart rate, systolic and diastolic blood pressure, pulse pressure|
| Hand	|Temperature and skin symptoms|
| Leg	|Exercise duration and bone mineral density|
  
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

##### Tabla de frecuencias por segmento
<div align="center">
  
|SEGMENTO [-]     |FRECUENCIA MEDIA (MNF) [Hz]     |FRECUENCIA MEDIANA (MDF) [Hz]     |FRECUENCIA PICO [HZ]  |  
|:-----:|:-----:|:-----:|:-----:|
|1     |59.00     |36.00     |24.00|     
|2     |73.31     |51.00     |43.00 |         
|3     |61.64     |41.00     |27.00  |        
|4     |72.77     |45.00     |42.00   |       
|5     |68.84     |42.00     |26.00   |
</div>




</div>
