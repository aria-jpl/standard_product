FROM hysds/isce2:latest-es1

MAINTAINER mkarim "Mohammed.R.Karim@jpl.nasa.gov"
LABEL description="standard_product"

ARG git_oauth_token
ARG id
ARG gid

# as ops user
USER ops
#RUN set -ex && \
 # usermod -u ${id} ops && \
  #groupmod -g ${gid} ops && \
  #chown -R ops:ops /home/ops/ /data && \
  #usermod -g ${gid} ops

# copy config
#COPY .aws /home/ops/.aws
#COPY .netrc /home/ops/.netrc

# copy packages
COPY . /home/ops/verdi/ops/standard_product

RUN $HOME/verdi/bin/pip install shapely
RUN $HOME/verdi/bin/pip install 'fiona==1.7.13'
RUN $HOME/verdi/bin/pip install 'pyproj==1.9.6'
RUN $HOME/verdi/bin/pip install 'geopandas==0.6.3'
RUN $HOME/verdi/bin/pip install elasticsearch
RUN $HOME/verdi/bin/pip install h5py
#RUN $HOME/verdi/bin/pip install basemap

USER root
#RUN yum install libgeos-3.6.2
#pip3 install https://github.com/matplotlib/basemap/archive/v1.1.0.tar.gz
#RUN $HOME/verdi/bin/pip3 install https://github.com/matplotlib/basemap/archive/v1.1.0.tar.gz

#USER root
RUN /opt/conda/bin/conda install --yes basemap opencv
#RUN ln -s /opt/conda/pkgs/basemap-*/share/basemap $HOME/verdi/share/basemap

USER ops
RUN $HOME/verdi/bin/pip install opencv-python
# create work directory
RUN set -ex \
 && mkdir -p /data/work \
 && chmod -R 755 /data \
 && chown -R ops:ops /data


RUN set -ex \
 && sudo chown -R ops:ops /home/ops/verdi/ops/standard_product \
 && mv /home/ops/verdi/ops/standard_product/multi_acquisition_localizer /home/ops/verdi/ops/ \
 && mv /home/ops/verdi/ops/standard_product/ariamh/ /home/ops/ 



WORKDIR /home/ops
CMD ["/bin/bash", "--login"]
