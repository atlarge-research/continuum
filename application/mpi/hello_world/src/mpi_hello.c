/******************************************************************************
 * FILE: mpi_hello.c
 * DESCRIPTION:
 *   MPI tutorial example code: Simple hello world program
 * AUTHOR: Blaise Barney
 * LAST REVISED: 03/05/10
 ******************************************************************************/
 #include "mpi.h"
 #include <stdio.h>
 #include <stdlib.h>
 
 int main(int argc, char *argv[])
 {
   int numtasks, taskid, len;
   char hostname[MPI_MAX_PROCESSOR_NAME];
 
   MPI_Init(&argc, &argv);
   MPI_Comm_size(MPI_COMM_WORLD, &numtasks);
   MPI_Comm_rank(MPI_COMM_WORLD, &taskid);
   MPI_Get_processor_name(hostname, &len);
 
   if (taskid == 0)
     printf("I am the master over %d workers!!! Muahahahahaa! \n", numtasks);
 
   MPI_Barrier(MPI_COMM_WORLD);
 
   printf("Hello from task %d on %s!\n", taskid, hostname);
 
   MPI_Finalize();
 }
 