[Skip to main content](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#page-container)

[![Terra Support Help Center home page](https://support.terra.bio/hc/theming_assets/01JKR249XXTP836H4HP922726H)](https://support.terra.bio/hc/en-us "Home")

- [Terra.bio](https://terra.bio/ "This link opens in a new tab")
- [Blog](https://terra.bio/blog/ "This link opens in a new tab")
- [Support Sitemap](https://support.terra.bio/hc/en-us/p/sitemap)
- [Terra App](https://app.terra.bio/ "This link opens in a new tab")
- [Community](https://support.terra.bio/hc/en-us/community/topics)
- [Submit a request](https://support.terra.bio/hc/en-us/requests/new)
- [Sign in](https://support.terra.bio/hc/en-us/signin?return_to=https%3A%2F%2Fsupport.terra.bio%2Fhc%2Fen-us%2Farticles%2F360024743371-Working-with-workspaces "Opens a dialog")

[Terra on Google Cloud](https://support.terra.bio/hc/en-us/categories/360001399872-Terra-on-Google-Cloud "This link opens in a new tab")

1. [Terra Support](https://support.terra.bio/hc/en-us)
2. [Terra on Google Cloud](https://support.terra.bio/hc/en-us/categories/360001399872-Terra-on-Google-Cloud)
3. [Workspaces](https://support.terra.bio/hc/en-us/sections/360004538992-Workspaces)

![](https://support.terra.bio/hc/theming_assets/01JBFAXRBPXXN69D8RV1FX8CKF)

# Working with workspaces

![](https://support.terra.bio/system/photos/360212213211/zendesk_profile.jpg)

[Anton Kovalsky](https://support.terra.bio/hc/en-us/profiles/376106466411-Anton-Kovalsky)

-
Updated
10 months ago
- [1 comment](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#comments)

FollowNot yet followed by anyone


In this article



- [Workspaces: All your analysis needs in one place](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#h_01EDYHDTHNDAZPTTGN7X0WDD1C)
- [Building workspaces using the Terra Library](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#h_01EDYMSPY5PCFV7MAD278SGRRM)

_Workspaces are the building blocks of Terra - a dedicated space where you and your collaborators can access and organize the same data and tools and run analyses together._

_Learn how to set up and use everything you need to collaborate in a Terra workspace._

Using Workspaces in Terra - YouTube

Tap to unmute

[Using Workspaces in Terra](https://www.youtube.com/watch?v=ONc1Wf7rEuw) [Terra](https://www.youtube-nocookie.com/channel/UCkXAqpR5Hk1ZmNd2-1K2l5Q)

Terra690 subscribers

[Watch on](https://www.youtube.com/watch?v=ONc1Wf7rEuw)

## Workspaces: All your analysis needs in one place

Your Terra workspace can contain data, metadata, and analysis tools, as well as documentation and a record of all workflow submissions. Each distinct component has its own page (see screenshot below), which you can access by clicking the tab at the top of any page. Expand the sections below for more details about how to access the resources you need.

![Screenshot showing an example workspace's tabs, which each allow different functions: Dashboard, Data, Analyses, Workflows, and Submission History.](https://support.terra.bio/hc/article_attachments/5795826299547)

- [Documentation in the Dashboard](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-0)




The landing page (i.e., **Dashboard**) is your project overview - the questions you’re trying to answer, the data and analysis tools you'll use, etc. Good documentation makes your analysis easy to share (with others, as well as with your future self) and reproduce.



#### Editing the dashboard (in the Markdown language)



Click the pencil icon to the right of the "About the Workspace" header at the top to edit. The dashboard uses the Markdown language, which lets you organize with headers and include links and additional references.



To learn more about Best Practices for documenting in a dashboard, see [Documentation best practices](https://support.terra.bio/hc/en-us/articles/360043450112).



![Screenshot of an example workspace's Dashboard tab. An orange arrow highlights the pencil icon, used to edit the description displayed on the dashboard.](https://support.terra.bio/hc/article_attachments/5795846363291)



Useful **workspace details** are populated automatically in the **right column of the Dashboard** (scroll down for screenshots). Expandable sections include:



#### Workspace information



The workspace creation date, date last updated, workflow submissions, and your access level.



#### Cloud information



The cloud infrastructure, location of workspace storage, Google Project ID, workspace storage ID, estimated storage cost and size. Here is where you can open the workspace storage file system (Google bucket structure in Google Cloud console).



#### Workspace owners



If you need access to the workspace, ask the workspace owners.



#### Workspace tags



Only visible to owners, tags are useful for searching and indexing.



|     |     |
| --- | --- |
| ![Screenshot showing the Workspace Information section displayed on an example workspace's dashboard.](https://support.terra.bio/hc/article_attachments/5796033810459)<br>![Screenshot showing the tags section displayed on an example workspace's dashboard.](https://support.terra.bio/hc/article_attachments/5796038489115) | ![Screenshot showing the Cloud Information section displayed on an example workspace's dashboard.](https://support.terra.bio/hc/article_attachments/5796035094299)<br>![Screenshot showing the Owners section displayed on an example workspace's dashboard.](https://support.terra.bio/hc/article_attachments/5796070110107) |

- [Store data in dedicated workspace storage](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-1)




Each workspace comes with its own storage (Google bucket) where data generated by a workflow analysis as well as interactive analysis files (i.e., notebook.ipynb and RStudio.Rmd files) are stored by default.



Additional workspace storage options (advanced) **Storage classes**

All newly created GCP workspace buckets will have Autoclass turned on by default. Autoclass automatically moves data to colder storage classes to reduce storage costs using a predefined lifecycle policy. There are no early deletion charges, no retrieval charges, and no charges for storage class transitions. For more information, see Google's [documentation on Autoclass](https://cloud.google.com/storage/docs/autoclass "This link opens in a new tab").







#### Storage region (location)



You can choose a specific region for your workspace storage when you create the workspace. See [Working with non-US data in Terra for more information](https://support.terra.bio/hc/en-us/articles/360060779892).



### To access the dedicated workspace storage



#### From the Dashboard



Select the **Open in browser** link in the **Cloud Information** section.



or



#### From the Data page



Click on the **Files** icon at the bottom of the left panel.



### Manual upload (best for a small number of small files)



#### Option 1: In Google Cloud console



Clicking the **Open bucket in browser link** in the **Cloud Information section** of the **Dashboard** will take you to the Google Cloud console, where you can **upload** smaller files from your local machine by **clicking or dragging.**

![alt](https://support.terra.bio/hc/article_attachments/5796905517339)



#### Option 2: In Terra



**Clicking the folder icon** on the right-hand panel of any workspace page will display the Workspace bucket file structure in the UI. You can upload files by clicking the **"upload" button** at the top left of this screen.

![Screenshot of the workspace file explorer for an example workspace. An orange box highlights the folder icon used to launch the file explorer. Another orange box highlights the 'Upload' button.](https://support.terra.bio/hc/article_attachments/37409426173339)



### gsutil (best for large numbers of files and/or large files)



You can also use gsutil in a terminal to copy data from a local machine or other cloud storage. To learn more, see [Using the terminal and interactive analysis shell](https://support.terra.bio/hc/en-us/articles/360041809272).

- [Manage and organize data in the Data page](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-2)




Like spreadsheets built right into the workspace, data tables help keep track of all project data, no matter where files are stored in the cloud. This becomes especially useful as the number of participants or samples in your study grows.



#### Genomic data



![Screenshot of genomic data in a sample table](https://support.terra.bio/hc/article_attachments/6815625781659)



#### Phenotypic data



![Screenshot of phenotypic data in a subjeect table](https://support.terra.bio/hc/article_attachments/6815663799323)



#### Tables spare you from copying/storing input data for a workflows analysis



In Terra, you can analyze data stored in the cloud without copying files to the workspace bucket. Workflows can input data using links to the data's actual location in the cloud from the table. And you can even write links to the generated files to the input table to associate it with the original.







Intro to Data Tables in Terra - YouTube


















Tap to unmute
















































[Intro to Data Tables in Terra](https://www.youtube.com/watch?v=vbUt6Uoryus) [Terra](https://www.youtube.com/channel/UCkXAqpR5Hk1ZmNd2-1K2l5Q)



![thumbnail-image](https://yt3.ggpht.com/ytc/AIdro_lZDahGuK7-wpVZKaG3AewPPiBzyKh8l4afw-aWC4foig=s68-c-k-c0x00ffffff-no-rj)



Terra690 subscribers



















































[Watch on](https://www.youtube.com/watch?v=vbUt6Uoryus)

































Learn how to combine data from different studies or across datasets in a single table in this video.







Making and Uploading a Data Table in Terra - YouTube


















Tap to unmute
















































[Making and Uploading a Data Table in Terra](https://www.youtube.com/watch?v=2MxSlKhIrFY) [Terra](https://www.youtube-nocookie.com/channel/UCkXAqpR5Hk1ZmNd2-1K2l5Q)



![thumbnail-image](https://yt3.ggpht.com/ytc/AIdro_lZDahGuK7-wpVZKaG3AewPPiBzyKh8l4afw-aWC4foig=s68-c-k-c0x00ffffff-no-rj)



Terra690 subscribers



















































[Watch on](https://www.youtube.com/watch?v=2MxSlKhIrFY)

- [Analyze and visualize data in real time with Galaxy, Jupyter Notebooks, or RStudio](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-3)




#### Interactive analysis - built into your workspace



Interrogate and visualize your data in real time using Galaxy, Jupyter Notebooks, or RStudio, Terra's integrated interactive analysis apps. All three apps run on virtual machines or clusters of machines in a workspace Cloud Environment.

![Screenshot of the Analyses tab](https://support.terra.bio/hc/article_attachments/5849231583003)



### Interactive app resources



  - [Your interactive analysis VM (Cloud Environment)](https://support.terra.bio/hc/en-us/articles/360038125912)

  - [Starting and customizing Galaxy on Terra](https://support.terra.bio/hc/en-us/articles/5075864021019)

  - [Interactive analysis with Jupyter notebooks](https://support.terra.bio/hc/en-us/articles/360024898671)

  - [Starting and customizing your RStudio app](https://support.terra.bio/hc/en-us/articles/360058138632)


- [Set up and run workflows (pipelines)](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-4)




Collect, configure (set up) and run workflows for bulk analyses from the **Workflows page**. Workflows are the sorts of repetitive analyses that can be automated, such as aligning sequencer reads or calling variants. You can set up and run a workflow by clicking on the workflow name in the card. Many options for saving costs - such as using [call caching](https://support.terra.bio/hc/en-us/articles/360047664872), [checkpointing](https://support.terra.bio/hc/en-us/articles/360056897032), or [preemptibles (spot VMs)](https://support.terra.bio/hc/en-us/articles/360029772212) \- are available in Terra.



![Screenshot showing the workflows available in an example workspace's Workflows tab.](https://support.terra.bio/hc/article_attachments/5843524830491)



#### Finding the workflow you need



Not a coding expert? Browse and import published workflows in Dockstore or the Broad Methods Repository by selecting the "Find a Workflow" card from the Workspaces page.



![Screenshow showing links to Dockstore and the Broad Methods Repository, from which you can import pre-written workflows into your Terra workspace.](https://support.terra.bio/hc/article_attachments/37409413988891)

- [Monitor and troubleshoot in the Submission History page](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-5)




The **Submission History** page (replaces Job History) is where you can check on the status of all current and past workflow submissions.



#### Troubleshooting



You can troubleshoot failed flows by selecting the workflow name in the "Submission" column at the left.



Read more in [How to troubleshoot failed workflows](https://support.terra.bio/hc/en-us/articles/360027920592).



![Screenshot showing the contents of an example workspace's Submission History tab, including a failed workflow. An orange box and orange arrow highlight the failed workflow's row, which is shaded red.](https://support.terra.bio/hc/article_attachments/6816512564507)



#### Error logs



See error messages (by hovering over the failed icon) and access further information (including error and log files) by clicking on the icons at right in the Submissions details page. ![Screenshot showing the submissions details page for an example workflow. An orange box and arrow highlight the icons listed in the 'links' column for one submission in the workflow.](https://support.terra.bio/hc/article_attachments/19844670001307)

- [Collaborate in a shared workspace](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces#zp-2-6)




To collaborate, you can "share" the project workspace with all the data, tools and generated data. Workspace owners control how much access collaborators have to resources, including funding, by assigning roles with different permission levels.



![Share-workspace_screen-capture.gif](https://support.terra.bio/hc/article_attachments/5849430619419)



Learn more in [Managing shared resources with groups and permissions](https://support.terra.bio/hc/en-us/articles/360024617851).


## Building workspaces using the Terra Library

Terra has three libraries that can help when building a workspace: **data**, **showcase workspaces**, and **tools** (workflows). To access the libraries, click the main menu icon (three horizontal lines) at the top left of any page and open the "Library" submenu.

![Screenshot of Terra Libraries in the main menu](https://support.terra.bio/hc/article_attachments/6816147479323)

To learn more about using the Terra Data Library to build your workspace, see [Build a workspace using data, showcase, and tools libraries](https://support.terra.bio/hc/en-us/articles/6810671342747).

#### Next article

[Soft delete for Terra workspace buckets](https://support.terra.bio/hc/en-us/articles/44168656111259-Soft-delete-for-Terra-workspace-buckets)

#### Was this article helpful?

6 out of 9 found this helpful

### That’s great, can you tell us why? (Click all that apply)

The article contained all the content I expected


It was easy to find the answer I was looking for in the article


The answer was useful and easy to understand


I feel confident that the content is accurate


Other


### Thanks for your feedback, help us improve by telling us what you think could be better (click all that apply)

The article didn’t contain the content I expected


It was difficult to find the answer I was looking for in the article


The answer was difficult to understand and/or use


I didn’t feel confident that the content is accurate


Other


Description

0/600

Submit feedback


Thank you for your feedback!


There was a problem submitting your feedback. Please try again later.


## Related articles

- [Build a workspace using data, showcase, and tools Library resources](https://support.terra.bio/hc/en-us/related/click?data=BAh7CjobZGVzdGluYXRpb25fYXJ0aWNsZV9pZGwrCJtkpbsxBjoYcmVmZXJyZXJfYXJ0aWNsZV9pZGwrCMudJdNTADoLbG9jYWxlSSIKZW4tdXMGOgZFVDoIdXJsSSJnL2hjL2VuLXVzL2FydGljbGVzLzY4MTA2NzEzNDI3NDctQnVpbGQtYS13b3Jrc3BhY2UtdXNpbmctZGF0YS1zaG93Y2FzZS1hbmQtdG9vbHMtTGlicmFyeS1yZXNvdXJjZXMGOwhUOglyYW5raQY%3D--238a5877ec09e92d627b6f51dcd217bab716100e)
- [How to add data to a workspace with a template](https://support.terra.bio/hc/en-us/related/click?data=BAh7CjobZGVzdGluYXRpb25fYXJ0aWNsZV9pZGwrCK8INNVTADoYcmVmZXJyZXJfYXJ0aWNsZV9pZGwrCMudJdNTADoLbG9jYWxlSSIKZW4tdXMGOgZFVDoIdXJsSSJTL2hjL2VuLXVzL2FydGljbGVzLzM2MDA1OTI0MjY3MS1Ib3ctdG8tYWRkLWRhdGEtdG8tYS13b3Jrc3BhY2Utd2l0aC1hLXRlbXBsYXRlBjsIVDoJcmFua2kH--531340995773d463f3497b82b083f566e105f53e)
- [Terra Data Repository (TDR): Overview](https://support.terra.bio/hc/en-us/related/click?data=BAh7CjobZGVzdGluYXRpb25fYXJ0aWNsZV9pZGwrCBvGPCQCBDoYcmVmZXJyZXJfYXJ0aWNsZV9pZGwrCMudJdNTADoLbG9jYWxlSSIKZW4tdXMGOgZFVDoIdXJsSSJIL2hjL2VuLXVzL2FydGljbGVzLzQ0MDcyNDQ0MDgzNDctVGVycmEtRGF0YS1SZXBvc2l0b3J5LVREUi1PdmVydmlldwY7CFQ6CXJhbmtpCA%3D%3D--6cb8e63a0e4e345c9ee085f2f864ad384fdfb292)
- [Upload data and populate the table with linked file paths](https://support.terra.bio/hc/en-us/related/click?data=BAh7CjobZGVzdGluYXRpb25fYXJ0aWNsZV9pZGwrCBvPcvoEBDoYcmVmZXJyZXJfYXJ0aWNsZV9pZGwrCMudJdNTADoLbG9jYWxlSSIKZW4tdXMGOgZFVDoIdXJsSSJfL2hjL2VuLXVzL2FydGljbGVzLzQ0MTk0MjgyMDg0MTEtVXBsb2FkLWRhdGEtYW5kLXBvcHVsYXRlLXRoZS10YWJsZS13aXRoLWxpbmtlZC1maWxlLXBhdGhzBjsIVDoJcmFua2kJ--5bea05ffe7e98d5613e59d1919c5448023bd172b)
- [How to access data with DRS URIs](https://support.terra.bio/hc/en-us/related/click?data=BAh7CjobZGVzdGluYXRpb25fYXJ0aWNsZV9pZGwrCJvpkeMIBjoYcmVmZXJyZXJfYXJ0aWNsZV9pZGwrCMudJdNTADoLbG9jYWxlSSIKZW4tdXMGOgZFVDoIdXJsSSJGL2hjL2VuLXVzL2FydGljbGVzLzY2MzUyNDc0OTU1NzktSG93LXRvLWFjY2Vzcy1kYXRhLXdpdGgtRFJTLVVSSXMGOwhUOglyYW5raQo%3D--1a51591e040609c76bad7dbae703100544e6b844)

### Comments

1 comment


Sort by
[Date](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces?sort_by=created_at) [Votes](https://support.terra.bio/hc/en-us/articles/360024743371-Working-with-workspaces?sort_by=votes)

- ![Comment author](https://support.terra.bio/system/photos/14190454947739/profile_image_14190415336475_2378360.jpg)



[Tadesse Worabo](https://support.terra.bio/hc/en-us/profiles/14190415336475-Tadesse-Worabo)

  - 3 years ago

Work

0

Please [sign in](https://broadinstitute.zendesk.com/access?locale=en-us&brand_id=360000963592&return_to=https%3A%2F%2Fsupport.terra.bio%2Fhc%2Fen-us%2Farticles%2F360024743371-Working-with-workspaces "This link opens in a new tab") to leave a comment.


### Categories

- [Platform-wide (security, status and updates)](https://support.terra.bio/hc/en-us/categories/360000693572-Platform-wide-security-status-and-updates)Open
  - [Terra Roadmap](https://support.terra.bio/hc/en-us/sections/30968105851931-Terra-Roadmap)

  - [Terra Essentials](https://support.terra.bio/hc/en-us/sections/27669386344475-Terra-Essentials)

  - [Security and Controls](https://support.terra.bio/hc/en-us/sections/4408251025563-Security-and-Controls)

  - [Release Notes](https://support.terra.bio/hc/en-us/sections/4414878945819-Release-Notes)

  - [Other scientific tools](https://support.terra.bio/hc/en-us/sections/28401921882779-Other-scientific-tools)

  - [Service Notifications](https://support.terra.bio/hc/en-us/sections/4415104213787-Service-Notifications)
- [Terra on Google Cloud](https://support.terra.bio/hc/en-us/categories/360001399872-Terra-on-Google-Cloud)Collapse
  - [Getting Started (GCP)](https://support.terra.bio/hc/en-us/sections/23504885621787-Getting-Started-GCP)

  - [Account and billing](https://support.terra.bio/hc/en-us/sections/360006958171-Account-and-billing)

  - [Managing Billing Access](https://support.terra.bio/hc/en-us/sections/29801938314779-Managing-Billing-Access)

  - [Managing Tools and Data Access](https://support.terra.bio/hc/en-us/sections/4408254216987-Managing-Tools-and-Data-Access)

  - [Managing Cloud costs](https://support.terra.bio/hc/en-us/sections/360006459511-Managing-Cloud-costs)

  - [Workspaces](https://support.terra.bio/hc/en-us/sections/360004538992-Workspaces)

  - [Data](https://support.terra.bio/hc/en-us/sections/360004147951-Data)

  - [Terra Data Repository](https://support.terra.bio/hc/en-us/sections/4407099323675-Terra-Data-Repository)

  - [Workflows](https://support.terra.bio/hc/en-us/sections/360004147011-Workflows)

  - [Interactive Analysis](https://support.terra.bio/hc/en-us/sections/360004143932-Interactive-Analysis)

  - [Working with Containers (Docker)](https://support.terra.bio/hc/en-us/sections/360003924192-Working-with-Containers-Docker)

  - [Troubleshooting](https://support.terra.bio/hc/en-us/sections/360007358272-Troubleshooting)

  - [Advanced resources](https://support.terra.bio/hc/en-us/sections/11327801799835-Advanced-resources)
- [Scientific Partnerships](https://support.terra.bio/hc/en-us/categories/4410648259355-Scientific-Partnerships)Open
  - [AnVIL](https://support.terra.bio/hc/en-us/sections/4408264011035-AnVIL)

  - [NHLBI BioData CatalystⓇ](https://support.terra.bio/hc/en-us/sections/4408259637403-NHLBI-BioData-Catalyst%E2%93%87)

  - [Human Cell Atlas](https://support.terra.bio/hc/en-us/sections/4408259510683-Human-Cell-Atlas)
- [Training Events](https://support.terra.bio/hc/en-us/categories/4408258911131-Training-Events)Open
  - [Previous Event Materials](https://support.terra.bio/hc/en-us/sections/360003513671-Previous-Event-Materials)
- [Sitemap](https://support.terra.bio/hc/p/sitemap)

### Resources

[Terra on GCP](https://support.terra.bio/hc/en-us/sections/23504885621787) [Terra Roadmap](https://support.terra.bio/hc/en-us/sections/30968105851931-Terra-Roadmap) [Community Forum](https://support.terra.bio/hc/en-us/community/topics) [WDLs Resources](https://docs.openwdl.org/ "This link opens in a new tab") [Terra Training](https://support.terra.bio/hc/en-us/categories/4408258911131-Training-Events) [Terra blog](https://terra.bio/blog/ "This link opens in a new tab") [Terra.bio](https://terra.bio/ "This link opens in a new tab")

### Scientific partners

[AnVIL](https://support.terra.bio/hc/en-us/sections/4408264011035) [BioData CATALYST](https://support.terra.bio/hc/en-us/sections/4408259637403) [Human Cell Atlas](https://www.humancellatlas.org/ "This link opens in a new tab")

### Platform-wide resources

[Legal & compliance](https://support.terra.bio/hc/en-us/sections/4408251025563-Legal-and-Compliance) [Release notes](https://support.terra.bio/hc/en-us/sections/4414878945819) [Service notifications](https://support.terra.bio/hc/en-us/sections/4415104213787)

### Social

[Twitter](https://twitter.com/TerraBioApp "This link opens in a new tab") [YouTube](https://bit.ly/terra-channel "This link opens in a new tab") [LinkedIn](https://www.youtube.com/redirect?event=video_description&redir_token=QUFFLUhqbEdqTGpSZjJTV2xPSEFsdUhlNGktYVU2V25yd3xBQ3Jtc0tsSXFSSzl1UGtBa3FSd0NZM1h3Nkg5bXBWV0d0U1YxWmhJSkhxYUxDVW9LT0ZNQVo5SnR0bHAxZU92alNmRl96d3h6b3MtVUR2cEZSbmE5TTNJZTluMFZ3RWZneGVkenExdHROSWpxNC1WcUJKLWZsRQ&q=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2Fterrabioapp "This link opens in a new tab")

![](https://support.terra.bio/hc/theming_assets/01JKR248TA7MVMTN5RRFF7EFXN)

Copyright © 2025 Terra Support. All Rights Reserved \| [Community Guidelines](https://support.terra.bio/hc/en-us/community/posts/360055072271-Terra-Community-Guidelines) \| [Terms of Service](https://terra.bio/about/terms-of-service/ "This link opens in a new tab") \| [app.terra.bio](https://app.terra.bio/ "This link opens in a new tab")

![](https://support.terra.bio/hc/theming_assets/01JBFAXRBPXXN69D8RV1FX8CKF)

Permalink