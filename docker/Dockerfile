FROM hysds/isce2

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
RUN pip install --upgrade pip
RUN pip3 install 'pyproj==1.9.6'
RUN pip install 'pyproj==1.9.6'
RUN pip install --upgrade --ignore-installed 'geopandas'
#RUN pip3 install --upgrade --ignore-installed 'geopandas'
RUN pip install shapely
RUN pip3 install shapely
RUN pip install numpy
RUN pip3 install numpy

RUN pip install 'fiona==1.7.13'
RUN pip3 install 'fiona==1.7.13'
#RUN pip3 install 'pyproj==1.9.6'
#RUN pip install 'pyproj==1.9.6'
#RUN pip install 'geopandas'
#RUN pip3 install 'geopandas'
RUN pip3 install elasticsearch
RUN pip install elasticsearch

RUN pip install shapely
RUN pip install 'fiona==1.7.13'
RUN pip install 'pyproj==1.9.6'
RUN pip install 'geopandas==0.6.3'
RUN pip install elasticsearch
RUN ln -s /opt/conda/pkgs/basemap-*/share/basemap $HOME/verdi/share/basemap


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
